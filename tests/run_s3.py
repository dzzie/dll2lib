#!/usr/bin/env python3
"""
S3 test -- full export handling: __imp__ slots + decoration folded into dll2lib.

Build a DLL with a __cdecl and a __stdcall export. The caller consumes BOTH via
__declspec(dllimport) (i.e. call-through `__imp__...`) and -- crucially -- has
NO /alternatename pragmas: dll2lib emits a .drectve section that bridges the
stdcall decoration (`_StdAdd@8`/`__imp__StdAdd@8` -> undecorated) itself.

    static volatile int g = 40;
    int __cdecl   CdeclGet(void)        { return g + 2; }     // 42
    int __stdcall StdAdd(int a, int b)  { return a + b + g; } // a+b+40

Caller: CdeclGet()==42 && StdAdd(100,100)==240 -> exit 42, with the DLL deleted.
"""
from __future__ import annotations
import os
import sys
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from pe32 import PE32                       # noqa: E402
from convert import convert                  # noqa: E402
from msvc import vcrun, find_tool            # noqa: E402

DLL_C = r"""
static volatile int g = 40;
int __cdecl   CdeclGet(void)       { return g + 2; }
int __stdcall StdAdd(int a, int b) { return a + b + g; }
"""
DLL_DEF = "LIBRARY testdll3\nEXPORTS\n    CdeclGet\n    StdAdd\n"

# NOTE: no #pragma linker alternatename here -- dll2lib supplies decoration.
CALLER_C = r"""
__declspec(dllimport) int __cdecl   CdeclGet(void);
__declspec(dllimport) int __stdcall StdAdd(int a, int b);
int main(void) {
    int c = CdeclGet();          /* 42 */
    int s = StdAdd(100, 100);    /* 100 + 100 + 40 = 240 */
    return (c == 42 && s == 240) ? 42 : 1;
}
"""


def step(ok_now: bool, label: str, detail: str = "") -> bool:
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s3_")
    print(f"build dir: {tmp}")
    ok = True

    open(os.path.join(tmp, "testdll3.c"), "w").write(DLL_C)
    open(os.path.join(tmp, "testdll3.def"), "w").write(DLL_DEF)

    vcrun("cl /nologo /c /O2 /GS- testdll3.c", tmp)
    vcrun("link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:testdll3.def "
          "/OUT:testdll3.dll testdll3.obj", tmp)
    dll = os.path.join(tmp, "testdll3.dll")
    ok = step(os.path.isfile(dll), "built cdecl+stdcall testdll3.dll") and ok
    if not os.path.isfile(dll):
        print("\nS3 FAIL"); return 1

    pe = PE32.from_file(dll)
    ok = step({e.name for e in pe.exports if e.name} == {"CdeclGet", "StdAdd"},
              "exports CdeclGet + StdAdd") and ok

    # CONVERT with decoration info for the stdcall export (8 arg-bytes)
    obj = convert(pe, stdcall_args={"StdAdd": 8})
    obj_path = os.path.join(tmp, "testdll3_s.obj")
    open(obj_path, "wb").write(obj)
    print(f"      converted obj: {len(obj)} bytes")

    db = find_tool("dumpbin.exe")
    if db:
        syms = subprocess.run([db, "/SYMBOLS", obj_path], capture_output=True, text=True).stdout
        # undecorated + __imp__ for both, plus DECORATED real symbols for stdcall
        for needle in ("_CdeclGet", "_StdAdd", "__imp__CdeclGet", "__imp__StdAdd",
                       "_StdAdd@8", "__imp__StdAdd@8"):
            ok = step(needle in syms, f"obj defines {needle}") and ok

    vcrun("lib /nologo /out:testdll3_s.lib testdll3_s.obj", tmp)
    ok = step(os.path.isfile(os.path.join(tmp, "testdll3_s.lib")),
              "lib.exe wrapped -> testdll3_s.lib") and ok

    # caller with NO pragmas, call-through dllimport for both
    open(os.path.join(tmp, "caller.c"), "w").write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testdll3_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe),
              "caller (dllimport, no pragmas) linked against our lib") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr)
        print("\nS3 FAIL"); return 1

    if db:
        imps = subprocess.run([db, "/IMPORTS", exe], capture_output=True, text=True).stdout
        ok = step("testdll3" not in imps.lower(), "t.exe has NO import on testdll3.dll") and ok

    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (DLL deleted) exit code",
              f"= {rr.returncode} (want 42)") and ok

    print(f"\n{'='*50}\nS3 {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
