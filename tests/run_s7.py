#!/usr/bin/env python3
"""
S7 (part 1) -- convert a REAL, idiomatic CRT-built DLL and run it.

Unlike S2-S6 (hand-minimized /NODEFAULTLIB /NOENTRY DLLs), this is a normal
C++ DLL built with the static CRT (/MT), /GS, a C++ global constructor, a
DllMain, and ~1800 base relocs -- exactly what a real compiler emits.

    static int g_sum;
    struct Setup { Setup(){ g_sum = 40; } };   // runs during CRT init (_initterm)
    static Setup g_setup;
    extern "C" __declspec(dllexport) int __stdcall Compute(int x){ return g_sum + x; }
    BOOL WINAPI DllMain(HINSTANCE,DWORD r,LPVOID){ if(r==DLL_PROCESS_ATTACH) g_sum+=2; return 1; }

So g_sum is 0 until init, then 40 (global ctor) + 2 (DllMain attach) = 42.
The caller proves Compute(0)==0 BEFORE StaticInit and ==42 AFTER -> the fused
DLL's entire CRT startup (ctors + DllMain) ran via our bootstrap. DLL deleted.
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

DLL_CPP = r"""
#include <windows.h>
static int g_sum;
struct Setup { Setup(){ g_sum = 40; } };
static Setup g_setup;
extern "C" __declspec(dllexport) int __stdcall Compute(int x) { return g_sum + x; }
BOOL WINAPI DllMain(HINSTANCE h, DWORD r, LPVOID p) {
    if (r == DLL_PROCESS_ATTACH) g_sum += 2;
    return TRUE;
}
"""
DLL_DEF = "LIBRARY testreal\nEXPORTS\n    Compute\n"
CALLER_C = r"""
__declspec(dllimport) int __stdcall Compute(int x);
extern void __cdecl testreal_StaticInit(void);
int main(void) {
    if (Compute(0) != 0) return 2;        /* uninitialized: C++ ctor hasn't run */
    testreal_StaticInit();                /* runs CRT init (ctors) + DllMain */
    return Compute(0) == 42 ? 42 : 1;     /* 40 (ctor) + 2 (DllMain) */
}
"""


def step(ok_now, label, detail=""):
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s7_")
    print(f"build dir: {tmp}")
    ok = True

    open(os.path.join(tmp, "testreal.cpp"), "w").write(DLL_CPP)
    open(os.path.join(tmp, "testreal.def"), "w").write(DLL_DEF)
    r = vcrun("cl /nologo /LD /MT /GS /EHsc testreal.cpp /link /DEF:testreal.def", tmp)
    dll = os.path.join(tmp, "testreal.dll")
    ok = step(os.path.isfile(dll), "built real /MT /GS C++ DLL (CRT + global ctor + DllMain)") and ok
    if not os.path.isfile(dll):
        print((r.stdout + r.stderr)[-800:]); print("\nS7 FAIL"); return 1

    pe = PE32.from_file(dll)
    print(f"      DLL: {len(pe.sections)} sections, {len(pe.relocs)} relocs, "
          f"imports {sorted({i.name for i in pe.imports})}, tls={pe.has_tls}, "
          f"entry=0x{pe.address_of_entry_point:X}")
    ok = step(pe.is_convertible, "real DLL is convertible (no refuse reasons)",
              f"{pe.refuse_reasons}") and ok
    ok = step(len(pe.relocs) > 500, "real reloc volume", f"({len(pe.relocs)} HIGHLOW)") and ok

    obj = convert(pe, stdcall_args={"Compute": 4}, init_symbol="_testreal_StaticInit")
    open(os.path.join(tmp, "testreal_s.obj"), "wb").write(obj)
    print(f"      converted obj: {len(obj)} bytes")

    rl = vcrun("lib /nologo /out:testreal_s.lib testreal_s.obj", tmp)
    ok = step(os.path.isfile(os.path.join(tmp, "testreal_s.lib")), "lib wrapped -> .lib") and ok
    if not os.path.isfile(os.path.join(tmp, "testreal_s.lib")):
        print(rl.stdout + rl.stderr)

    open(os.path.join(tmp, "caller.c"), "w").write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testreal_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe), "caller linked against the fused lib") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr); print("\nS7 FAIL"); return 1

    db = find_tool("dumpbin.exe")
    if db:
        imps = subprocess.run([db, "/IMPORTS", exe], capture_output=True, text=True).stdout
        ok = step("testreal" not in imps.lower(), "t.exe has NO import on testreal.dll") and ok

    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (DLL deleted) exit code",
              f"= {rr.returncode} (want 42: ctor+DllMain ran via bootstrap)") and ok

    print(f"\n{'='*50}\nS7(1) {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
