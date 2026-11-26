#!/usr/bin/env python3
r"""
trace_build.py  -  investigation probe for the VB6 fusion leg.

Launches  VB6.EXE /make <proj.vbp>  as a DEBUGGED process (debugs children too)
and logs every child process it spawns with the full image path and command
line, snapshotting *.obj / *.rsp at each spawn. Tells us how VB6 invokes the
linker and whether the OBJs are grabbable at that moment. Zero footprint.

Usage:  python trace_build.py <project.vbp> [outdir]
(64-bit Python debugging the 32-bit VB6/LINK via the WOW64 PEB.)
"""
import os
import sys
import struct
import ctypes as C
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
ntdll = C.WinDLL("ntdll")

DEBUG_PROCESS = 0x00000001
INFINITE = 0xFFFFFFFF
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DE, CREATE_PROCESS_DE, EXIT_PROCESS_DE, LOAD_DLL_DE = 1, 3, 5, 6
BREAKPOINTS = (0x80000003, 0x4000001F)
ProcessWow64Information = 26


class STARTUPINFOW(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR),
                ("lpTitle", W.LPWSTR), ("dwX", W.DWORD), ("dwY", W.DWORD),
                ("dwXSize", W.DWORD), ("dwYSize", W.DWORD), ("dwXCountChars", W.DWORD),
                ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", C.c_void_p), ("hStdInput", W.HANDLE),
                ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class PROCESS_INFORMATION(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


class EXCEPTION_RECORD(C.Structure):
    _fields_ = [("ExceptionCode", W.DWORD), ("ExceptionFlags", W.DWORD),
                ("ExceptionRecord", C.c_void_p), ("ExceptionAddress", C.c_void_p),
                ("NumberParameters", W.DWORD), ("ExceptionInformation", C.c_void_p * 15)]


class EXCEPTION_DEBUG_INFO(C.Structure):
    _fields_ = [("ExceptionRecord", EXCEPTION_RECORD), ("dwFirstChance", W.DWORD)]


class CREATE_PROCESS_DEBUG_INFO(C.Structure):
    _fields_ = [("hFile", W.HANDLE), ("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("lpBaseOfImage", C.c_void_p), ("dwDebugInfoFileOffset", W.DWORD),
                ("nDebugInfoSize", W.DWORD), ("lpThreadLocalBase", C.c_void_p),
                ("lpStartAddress", C.c_void_p), ("lpImageName", C.c_void_p),
                ("fUnicode", W.WORD)]


class EXIT_PROCESS_DEBUG_INFO(C.Structure):
    _fields_ = [("dwExitCode", W.DWORD)]


class LOAD_DLL_DEBUG_INFO(C.Structure):
    _fields_ = [("hFile", W.HANDLE), ("lpBaseOfDll", C.c_void_p),
                ("dwDebugInfoFileOffset", W.DWORD), ("nDebugInfoSize", W.DWORD),
                ("lpImageName", C.c_void_p), ("fUnicode", W.WORD)]


class DE_UNION(C.Union):
    _fields_ = [("Exception", EXCEPTION_DEBUG_INFO),
                ("CreateProcessInfo", CREATE_PROCESS_DEBUG_INFO),
                ("ExitProcess", EXIT_PROCESS_DEBUG_INFO),
                ("LoadDll", LOAD_DLL_DEBUG_INFO),
                ("raw", C.c_byte * 256)]


class DEBUG_EVENT(C.Structure):
    _fields_ = [("dwDebugEventCode", W.DWORD), ("dwProcessId", W.DWORD),
                ("dwThreadId", W.DWORD), ("u", DE_UNION)]


k32.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL,
                               W.DWORD, C.c_void_p, W.LPCWSTR, C.c_void_p, C.c_void_p]
k32.CreateProcessW.restype = W.BOOL
k32.WaitForDebugEvent.argtypes = [C.POINTER(DEBUG_EVENT), W.DWORD]
k32.WaitForDebugEvent.restype = W.BOOL
k32.ContinueDebugEvent.argtypes = [W.DWORD, W.DWORD, W.DWORD]
k32.ContinueDebugEvent.restype = W.BOOL
k32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
k32.QueryFullProcessImageNameW.restype = W.BOOL
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.ReadProcessMemory.restype = W.BOOL
k32.CloseHandle.argtypes = [W.HANDLE]
k32.CloseHandle.restype = W.BOOL
ntdll.NtQueryInformationProcess.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.ULONG,
                                            C.POINTER(W.ULONG)]
ntdll.NtQueryInformationProcess.restype = C.c_long


def child_image_path(hproc):
    buf = C.create_unicode_buffer(32768)
    sz = W.DWORD(len(buf))
    if k32.QueryFullProcessImageNameW(hproc, 0, buf, C.byref(sz)):
        return buf.value
    return "(unknown)"


def rpm(hproc, addr, size):
    buf = (C.c_char * size)()
    read = C.c_size_t(0)
    if not k32.ReadProcessMemory(hproc, C.c_void_p(addr), buf, size, C.byref(read)):
        return None
    return bytes(buf[:read.value])


def child_cmdline(hproc):
    peb32 = C.c_void_p(0)
    if ntdll.NtQueryInformationProcess(hproc, ProcessWow64Information,
                                       C.byref(peb32), C.sizeof(peb32), None) != 0:
        return "(NtQIP failed)"
    if not peb32.value:
        return "(not WOW64)"
    pp_raw = rpm(hproc, peb32.value + 0x10, 4)       # 32-bit PEB.ProcessParameters
    if not pp_raw:
        return "(peb read failed)"
    pp = struct.unpack("<I", pp_raw)[0]
    cl = rpm(hproc, pp + 0x40, 8)                    # CommandLine UNICODE_STRING (32-bit)
    if not cl:
        return "(params read failed)"
    length, _m, buf_ptr = struct.unpack("<HHI", cl)
    data = rpm(hproc, buf_ptr, length)
    return data.decode("utf-16le", "replace") if data else "(cmdline read failed)"


def snapshot(label, dirs):
    print(f"    [{label}] obj/rsp/lib present:")
    found = False
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for f in names:
            if f.lower().endswith((".obj", ".rsp", ".lib")):
                p = os.path.join(d, f)
                try:
                    print(f"        {p}  ({os.path.getsize(p)} bytes)")
                except OSError:
                    print(f"        {p}")
                found = True
    if not found:
        print("        (none)")


def main():
    if len(sys.argv) < 2:
        print("usage: trace_build.py <project.vbp> [outdir]"); return 2
    vbp = os.path.abspath(sys.argv[1])
    proj_dir = os.path.dirname(vbp)
    outdir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else proj_dir
    watch = [proj_dir, outdir, os.environ.get("TEMP", "")]

    VB6 = r"C:\Program Files (x86)\Microsoft Visual Studio\VB98\VB6.EXE"
    log = os.path.join(outdir, "vb6_make.log")
    cmd = f'"{VB6}" /make "{vbp}" /out "{log}" /outdir "{outdir}"'
    print("launching (debugged):", cmd)

    si = STARTUPINFOW(); si.cb = C.sizeof(si)
    pi = PROCESS_INFORMATION()
    if not k32.CreateProcessW(VB6, C.c_wchar_p(cmd), None, None, False,
                              DEBUG_PROCESS, None, proj_dir, C.byref(si), C.byref(pi)):
        print("CreateProcess failed:", C.get_last_error()); return 1
    root_pid = pi.dwProcessId
    seen_bp = set()

    evt = DEBUG_EVENT()
    while True:
        if not k32.WaitForDebugEvent(C.byref(evt), INFINITE):
            break
        status = DBG_CONTINUE
        code = evt.dwDebugEventCode

        if code == CREATE_PROCESS_DE:
            info = evt.u.CreateProcessInfo
            path = child_image_path(info.hProcess)
            cl = child_cmdline(info.hProcess)
            tag = "ROOT" if evt.dwProcessId == root_pid else "CHILD"
            print(f"\n[{tag} pid {evt.dwProcessId}] CREATE_PROCESS: {path}")
            print(f"    cmdline: {cl}")
            if "link" in os.path.basename(path).lower():
                print("    >>> LINKER spawned <<<")
                snapshot("at-linker-spawn", watch)
                # capture the OBJs + link cmdline before VB6 deletes them
                import shutil
                cap = os.path.join(outdir, "captured")
                os.makedirs(cap, exist_ok=True)
                for f in os.listdir(proj_dir):
                    if f.lower().endswith(".obj"):
                        try:
                            shutil.copy2(os.path.join(proj_dir, f), os.path.join(cap, f))
                        except OSError as e:
                            print(f"      copy {f} failed: {e}")
                with open(os.path.join(cap, "link_cmd.txt"), "w") as lf:
                    lf.write(cl + "\n")
                print(f"    captured OBJs + link_cmd.txt -> {cap}")
            if info.hFile:
                k32.CloseHandle(info.hFile)

        elif code == LOAD_DLL_DE:
            if evt.u.LoadDll.hFile:
                k32.CloseHandle(evt.u.LoadDll.hFile)

        elif code == EXCEPTION_DE:
            exc = evt.u.Exception.ExceptionRecord.ExceptionCode
            if exc in BREAKPOINTS:
                status = DBG_CONTINUE
                seen_bp.add(evt.dwProcessId)
            else:
                status = DBG_EXCEPTION_NOT_HANDLED

        elif code == EXIT_PROCESS_DE:
            tag = "ROOT" if evt.dwProcessId == root_pid else "CHILD"
            print(f"[{tag} pid {evt.dwProcessId}] EXIT_PROCESS code={evt.u.ExitProcess.dwExitCode}")

        k32.ContinueDebugEvent(evt.dwProcessId, evt.dwThreadId, status)
        if code == EXIT_PROCESS_DE and evt.dwProcessId == root_pid:
            break

    print("\n==== post-build snapshot ====")
    snapshot("after-build", watch)
    if os.path.isfile(log):
        print("\n==== vb6 make log ====")
        print(open(log, "r", errors="replace").read().strip() or "(empty = success)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
