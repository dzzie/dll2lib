#!/usr/bin/env python3
"""
S2 SPINE test -- the pivotal end-to-end proof.

Build a tiny real __stdcall DLL with cl/link, convert it to a static .lib with
dll2lib, link that .lib into a C caller, DELETE the DLL, and prove the exported
functions still run correctly -- i.e. the DLL's code now lives inside the exe.

Test DLL (no imports, no CRT, no DllMain; one global => one real code->data
HIGHLOW reloc to convert):

    static volatile int g_bias = 100;                 // volatile so /O2 keeps the load
    int __stdcall AddNumbers(int a,int b){ return a+b+g_bias; }   // uses a reloc
    int __stdcall MulNumbers(int a,int b){ return a*b; }          // no reloc

Caller: AddNumbers(20,22) must be 142, MulNumbers(6,7) must be 42 -> exit 42.
Exit 0 iff green AND the exe has no dependency on testdll.dll.
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

TESTDLL_C = r"""
static volatile int g_bias = 100;
int __stdcall AddNumbers(int a, int b) { return a + b + g_bias; }
int __stdcall MulNumbers(int a, int b) { return a * b; }
"""

TESTDLL_DEF = "LIBRARY testdll\nEXPORTS\n    AddNumbers\n    MulNumbers\n"

CALLER_C = r"""
#pragma comment(linker, "/alternatename:_AddNumbers@8=_AddNumbers")
#pragma comment(linker, "/alternatename:_MulNumbers@8=_MulNumbers")
extern int __stdcall AddNumbers(int a, int b);
extern int __stdcall MulNumbers(int a, int b);
int main(void) {
    int a = AddNumbers(20, 22);   /* 20 + 22 + 100 = 142 */
    int m = MulNumbers(6, 7);     /* 42 */
    return (a == 142 && m == 42) ? 42 : 1;
}
"""


def step(ok_now: bool, label: str, detail: str = "") -> bool:
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s2_")
    print(f"build dir: {tmp}")
    ok = True

    with open(os.path.join(tmp, "testdll.c"), "w") as f:
        f.write(TESTDLL_C)
    with open(os.path.join(tmp, "testdll.def"), "w") as f:
        f.write(TESTDLL_DEF)

    # 1) compile + link the real stdcall DLL (no CRT, no entry)
    r = vcrun("cl /nologo /c /O2 /GS- testdll.c", tmp)
    r2 = vcrun("link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:testdll.def "
               "/OUT:testdll.dll testdll.obj", tmp)
    dll = os.path.join(tmp, "testdll.dll")
    ok = step(os.path.isfile(dll), "built real stdcall testdll.dll") and ok
    if not os.path.isfile(dll):
        print(r.stdout + r.stderr + r2.stdout + r2.stderr)
        print("\nS2 FAIL"); return 1

    # 2) parse + sanity: it must actually have a HIGHLOW reloc to convert
    pe = PE32.from_file(dll)
    nhl = pe.reloc_type_counts.get(3, 0)
    ok = step(nhl >= 1, "DLL has >=1 HIGHLOW reloc to convert", f"({nhl} found)") and ok
    ok = step({e.name for e in pe.exports if e.name} == {"AddNumbers", "MulNumbers"},
              "exports AddNumbers + MulNumbers") and ok
    ok = step(len(pe.imports) == 0, "DLL has no imports (spine precondition)",
              f"({len(pe.imports)} imports)") and ok

    # 3) CONVERT -> our COFF object
    obj = convert(pe)
    obj_path = os.path.join(tmp, "testdll_s.obj")
    with open(obj_path, "wb") as f:
        f.write(obj)
    print(f"      converted obj: {len(obj)} bytes")

    db = find_tool("dumpbin.exe")
    if db:
        out = subprocess.run([db, "/SYMBOLS", "/RELOCATIONS", obj_path],
                             capture_output=True, text=True).stdout
        ok = step(("_AddNumbers" in out and "_MulNumbers" in out and "DIR32" in out),
                  "our obj has _AddNumbers/_MulNumbers + a DIR32 reloc") and ok

    # 4) lib.exe wraps -> static lib
    rl = vcrun("lib /nologo /out:testdll_s.lib testdll_s.obj", tmp)
    ok = step(os.path.isfile(os.path.join(tmp, "testdll_s.lib")),
              "lib.exe wrapped our obj -> testdll_s.lib") and ok
    if not os.path.isfile(os.path.join(tmp, "testdll_s.lib")):
        print(rl.stdout + rl.stderr)

    # 5) link the caller against our static lib
    with open(os.path.join(tmp, "caller.c"), "w") as f:
        f.write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testdll_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe), "cl+link produced t.exe (static)") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr)
        print("\nS2 FAIL"); return 1

    # 6) prove independence: exe must NOT import testdll.dll
    if db:
        imps = subprocess.run([db, "/IMPORTS", exe], capture_output=True, text=True).stdout
        ok = step("testdll" not in imps.lower(), "t.exe has NO import on testdll.dll") and ok

    # 7) delete the DLL, then run -- must still return 42
    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (with DLL deleted) exit code",
              f"= {rr.returncode} (want 42)") and ok

    print(f"\n{'='*50}\nS2 {'PASS -- KABOOM' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
