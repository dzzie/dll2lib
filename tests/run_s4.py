#!/usr/bin/env python3
"""
S4 test -- import rebuild. Convert a DLL that CALLS another DLL.

The test DLL imports kernel32!lstrlenA and exports StrLen() = lstrlenA("hello
world") = 11. dll2lib must rebuild kernel32's import as .idata$2/3/4/5/6 so the
final exe's import directory pulls lstrlenA, and redirect the DLL's IAT-slot
reference to the rebuilt .idata$5. Delete the DLL -> StrLen() must still be 11.
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
__declspec(dllimport) int __stdcall lstrlenA(const char* s);
int __stdcall StrLen(void) { return lstrlenA("hello world"); }
"""
DLL_DEF = "LIBRARY testdll4\nEXPORTS\n    StrLen\n"
CALLER_C = r"""
__declspec(dllimport) int __stdcall StrLen(void);
int main(void) { return StrLen() == 11 ? 42 : 1; }
"""


def step(ok_now: bool, label: str, detail: str = "") -> bool:
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s4_")
    print(f"build dir: {tmp}")
    ok = True

    open(os.path.join(tmp, "testdll4.c"), "w").write(DLL_C)
    open(os.path.join(tmp, "testdll4.def"), "w").write(DLL_DEF)
    vcrun("cl /nologo /c /O2 /GS- testdll4.c", tmp)
    r = vcrun("link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:testdll4.def "
              "kernel32.lib /OUT:testdll4.dll testdll4.obj", tmp)
    dll = os.path.join(tmp, "testdll4.dll")
    ok = step(os.path.isfile(dll), "built testdll4.dll (imports kernel32!lstrlenA)") and ok
    if not os.path.isfile(dll):
        print(r.stdout + r.stderr); print("\nS4 FAIL"); return 1

    pe = PE32.from_file(dll)
    imp_names = {i.name.lower() for i in pe.imports}
    ok = step(any("kernel32" in n for n in imp_names), "DLL imports kernel32",
              f"({sorted(imp_names)})") and ok
    syms_imported = {t.name for i in pe.imports for t in i.thunks}
    ok = step("lstrlenA" in syms_imported, "DLL imports lstrlenA by name") and ok

    obj = convert(pe, stdcall_args={"StrLen": 0})
    obj_path = os.path.join(tmp, "testdll4_s.obj")
    open(obj_path, "wb").write(obj)
    print(f"      converted obj: {len(obj)} bytes")

    db = find_tool("dumpbin.exe")
    if db:
        out = subprocess.run([db, "/HEADERS", obj_path], capture_output=True, text=True).stdout
        for needle in (".idata$2", ".idata$5", ".idata$6"):
            ok = step(needle in out, f"obj has section {needle}") and ok
    # name strings live in .idata$6 raw data -> search the obj bytes
    low = obj.lower()
    ok = step(b"lstrlena" in low, "obj .idata$6 contains the import name lstrlenA") and ok
    ok = step(b"kernel32" in low, "obj .idata$6 contains the DLL name kernel32") and ok

    vcrun("lib /nologo /out:testdll4_s.lib testdll4_s.obj", tmp)
    ok = step(os.path.isfile(os.path.join(tmp, "testdll4_s.lib")),
              "lib.exe wrapped -> testdll4_s.lib") and ok

    open(os.path.join(tmp, "caller.c"), "w").write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testdll4_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe), "cl+link produced t.exe") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr); print("\nS4 FAIL"); return 1

    if db:
        imps = subprocess.run([db, "/IMPORTS", exe], capture_output=True, text=True).stdout
        ok = step("lstrlena" in imps.lower(), "t.exe import table pulls kernel32!lstrlenA") and ok
        ok = step("testdll4" not in imps.lower(), "t.exe has NO import on testdll4.dll") and ok

    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (DLL deleted) exit code",
              f"= {rr.returncode} (want 42, i.e. StrLen()==11)") and ok

    print(f"\n{'='*50}\nS4 {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
