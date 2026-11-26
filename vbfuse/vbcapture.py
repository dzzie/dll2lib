#!/usr/bin/env python3
r"""
vbcapture.py  -  run VB6.EXE /make under a Win32 debugger and capture, at the
moment LINK.EXE spawns, the object files (which VB6 deletes after linking) and
the exact linker command line.

capture(vbp, workdir) -> CaptureResult(objs=[paths], link_cmd=str, ok=bool)

64-bit Python debugging the 32-bit VB6/LINK toolchain. Zero footprint.
"""
from __future__ import annotations
import os
import shutil
import struct
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass, field

k32 = C.WinDLL("kernel32", use_last_error=True)
ntdll = C.WinDLL("ntdll")

DEBUG_PROCESS = 0x00000001
INFINITE = 0xFFFFFFFF
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DE, CREATE_PROCESS_DE, EXIT_PROCESS_DE, LOAD_DLL_DE = 1, 3, 5, 6
BREAKPOINTS = (0x80000003, 0x4000001F)
ProcessWow64Information = 26
VB6_EXE = r"C:\Program Files (x86)\Microsoft Visual Studio\VB98\VB6.EXE"


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
                ("LoadDll", LOAD_DLL_DEBUG_INFO), ("raw", C.c_byte * 256)]


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
k32.CloseHandle.argtypes = [W.HANDLE]; k32.CloseHandle.restype = W.BOOL
ntdll.NtQueryInformationProcess.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.ULONG,
                                            C.POINTER(W.ULONG)]
ntdll.NtQueryInformationProcess.restype = C.c_long


@dataclass
class CaptureResult:
    objs: list = field(default_factory=list)
    link_cmd: str = ""
    ok: bool = False
    log: str = ""


def _obj_tokens(cmd: str):
    """Quote-aware extraction of the *.OBJ paths from a link command line."""
    toks, cur, inq, started = [], "", False, False
    for ch in cmd:
        if ch == '"':
            inq = not inq; started = True
        elif ch in " \t" and not inq:
            if started:
                toks.append(cur); cur = ""; started = False
        else:
            cur += ch; started = True
    if started:
        toks.append(cur)
    return [t for t in toks if t.lower().endswith(".obj")]


def _image_path(hproc):
    buf = C.create_unicode_buffer(32768); sz = W.DWORD(len(buf))
    return buf.value if k32.QueryFullProcessImageNameW(hproc, 0, buf, C.byref(sz)) else ""


def _rpm(hproc, addr, size):
    buf = (C.c_char * size)(); read = C.c_size_t(0)
    if not k32.ReadProcessMemory(hproc, C.c_void_p(addr), buf, size, C.byref(read)):
        return None
    return bytes(buf[:read.value])


def _cmdline(hproc):
    peb32 = C.c_void_p(0)
    if ntdll.NtQueryInformationProcess(hproc, ProcessWow64Information,
                                       C.byref(peb32), C.sizeof(peb32), None) != 0 or not peb32.value:
        return ""
    pp = _rpm(hproc, peb32.value + 0x10, 4)
    if not pp:
        return ""
    pp = struct.unpack("<I", pp)[0]
    cl = _rpm(hproc, pp + 0x40, 8)
    if not cl:
        return ""
    length, _m, bufp = struct.unpack("<HHI", cl)
    data = _rpm(hproc, bufp, length)
    return data.decode("utf-16le", "replace") if data else ""


def capture(vbp: str, workdir: str, verbose: bool = False) -> CaptureResult:
    vbp = os.path.abspath(vbp)
    proj_dir = os.path.dirname(vbp)
    os.makedirs(workdir, exist_ok=True)
    log = os.path.join(workdir, "vb6_make.log")
    cmd = f'"{VB6_EXE}" /make "{vbp}" /out "{log}" /outdir "{workdir}"'
    res = CaptureResult()

    si = STARTUPINFOW(); si.cb = C.sizeof(si)
    pi = PROCESS_INFORMATION()
    if not k32.CreateProcessW(VB6_EXE, C.c_wchar_p(cmd), None, None, False,
                              DEBUG_PROCESS, None, proj_dir, C.byref(si), C.byref(pi)):
        raise OSError(f"CreateProcess(VB6) failed: {C.get_last_error()}")
    root = pi.dwProcessId

    evt = DEBUG_EVENT()
    while True:
        if not k32.WaitForDebugEvent(C.byref(evt), INFINITE):
            break
        status = DBG_CONTINUE
        code = evt.dwDebugEventCode
        if code == CREATE_PROCESS_DE:
            info = evt.u.CreateProcessInfo
            path = _image_path(info.hProcess)
            if path and "link" in os.path.basename(path).lower():
                res.link_cmd = _cmdline(info.hProcess)
                # preserve the exact OBJ paths named on the link line into a
                # dedicated subdir (VB6 deletes the originals after linking).
                preserve = os.path.join(workdir, "obj")
                os.makedirs(preserve, exist_ok=True)
                for src in _obj_tokens(res.link_cmd):
                    dst = os.path.join(preserve, os.path.basename(src))
                    try:
                        shutil.copy2(src, dst)
                        res.objs.append(dst)
                    except OSError as e:
                        if verbose:
                            print(f"[vbcapture] copy {src} failed: {e}")
                if verbose:
                    print(f"[vbcapture] linker spawned; captured {len(res.objs)} objs")
            if info.hFile:
                k32.CloseHandle(info.hFile)
        elif code == LOAD_DLL_DE:
            if evt.u.LoadDll.hFile:
                k32.CloseHandle(evt.u.LoadDll.hFile)
        elif code == EXCEPTION_DE:
            if evt.u.Exception.ExceptionRecord.ExceptionCode not in BREAKPOINTS:
                status = DBG_EXCEPTION_NOT_HANDLED
        k32.ContinueDebugEvent(evt.dwProcessId, evt.dwThreadId, status)
        if code == EXIT_PROCESS_DE and evt.dwProcessId == root:
            break

    if os.path.isfile(log):
        res.log = open(log, "r", errors="replace").read().strip()
    res.ok = ("succeeded" in res.log.lower()) and bool(res.objs) and bool(res.link_cmd)
    return res
