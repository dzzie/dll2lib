#!/usr/bin/env python3
"""
S6 test -- DllMain/CRT bootstrap.

The test DLL has a custom entry point that sets a global ONLY when called with
DLL_PROCESS_ATTACH. If dll2lib's bootstrap correctly calls the DLL's entry, the
global flips 0 -> 42. The caller verifies it is 0 BEFORE StaticInit and 42
AFTER -- proving the bootstrap ran the entry (this is the same mechanism a real
CRT DLL needs, where the entry is DllMainCRTStartup).

    static volatile int g_init = 0;
    int __stdcall MyEntry(void* h, unsigned reason, void* r) {
        if (reason == 1) g_init = 42;      // DLL_PROCESS_ATTACH
        return 1;
    }
    __declspec(dllexport) int __stdcall GetVal(void) { return g_init; }
"""
from __future__ import annotations
import os
import sys
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from pe32 import PE32          # noqa: E402
from convert import convert    # noqa: E402
from msvc import vcrun, find_tool  # noqa: E402

DLL_C = r"""
static volatile int g_init = 0;
int __stdcall MyEntry(void* h, unsigned reason, void* r) {
    if (reason == 1) g_init = 42;
    return 1;
}
__declspec(dllexport) int __stdcall GetVal(void) { return g_init; }
"""
DLL_DEF = "LIBRARY testdll6\nEXPORTS\n    GetVal\n"
CALLER_C = r"""
__declspec(dllimport) int __stdcall GetVal(void);
extern void __cdecl testdll6_StaticInit(void);
int main(void) {
    if (GetVal() != 0) return 1;        /* not initialized yet */
    testdll6_StaticInit();              /* must run the DLL entry (DLL_PROCESS_ATTACH) */
    return GetVal() == 42 ? 42 : 1;
}
"""


def step(ok_now, label, detail=""):
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s6_")
    print(f"build dir: {tmp}")
    ok = True

    open(os.path.join(tmp, "testdll6.c"), "w").write(DLL_C)
    open(os.path.join(tmp, "testdll6.def"), "w").write(DLL_DEF)
    vcrun("cl /nologo /c /O2 /GS- testdll6.c", tmp)
    dll = os.path.join(tmp, "testdll6.dll")
    for entry in ("MyEntry@12", "_MyEntry@12"):
        vcrun(f"link /nologo /DLL /NODEFAULTLIB /ENTRY:{entry} /DEF:testdll6.def "
              f"/OUT:testdll6.dll testdll6.obj", tmp)
        if os.path.isfile(dll):
            break
    ok = step(os.path.isfile(dll), "built testdll6.dll with a custom entry") and ok
    if not os.path.isfile(dll):
        print("\nS6 FAIL"); return 1

    pe = PE32.from_file(dll)
    ok = step(pe.address_of_entry_point != 0, "DLL has a nonzero entry point",
              f"(RVA 0x{pe.address_of_entry_point:X})") and ok

    obj = convert(pe, stdcall_args={"GetVal": 0}, init_symbol="_testdll6_StaticInit")
    open(os.path.join(tmp, "testdll6_s.obj"), "wb").write(obj)
    print(f"      converted obj: {len(obj)} bytes")

    db = find_tool("dumpbin.exe")
    if db:
        out = subprocess.run([db, "/HEADERS", "/SYMBOLS", os.path.join(tmp, "testdll6_s.obj")],
                             capture_output=True, text=True).stdout
        ok = step(".binit" in out, "obj has a .binit bootstrap section") and ok
        ok = step("_testdll6_StaticInit" in out, "obj defines _testdll6_StaticInit") and ok
        ok = step("___ImageBase" in out, "obj references ___ImageBase (hinstDLL)") and ok

    vcrun("lib /nologo /out:testdll6_s.lib testdll6_s.obj", tmp)
    ok = step(os.path.isfile(os.path.join(tmp, "testdll6_s.lib")), "lib wrapped -> .lib") and ok

    open(os.path.join(tmp, "caller.c"), "w").write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testdll6_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe), "caller linked (calls StaticInit then GetVal)") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr); print("\nS6 FAIL"); return 1

    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (DLL deleted) exit code",
              f"= {rr.returncode} (want 42: 0 before init, 42 after -> bootstrap ran the entry)") and ok

    print(f"\n{'='*50}\nS6 {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
