#!/usr/bin/env python3
"""
S7 (part 4) -- resources skipped gracefully. v1 drops the DLL's .rsrc section
(resource APIs on the fused code won't find them -- a documented v1 limitation).
A DLL that merely *carries* resources but doesn't read them from its own code
must still convert and run its exported logic correctly.
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
static volatile int g = 42;              /* a global -> at least one reloc to convert */
int __stdcall Answer(void) { return g; }
"""
DLL_DEF = "LIBRARY testrsrc\nEXPORTS\n    Answer\n"
DLL_RC = r"""
#define IDS_HELLO 1
STRINGTABLE
BEGIN
    IDS_HELLO "hello from resources"
END
"""
CALLER_C = r"""
__declspec(dllimport) int __stdcall Answer(void);
int main(void) { return Answer() == 42 ? 42 : 1; }
"""


def step(ok_now, label, detail=""):
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s7r_")
    print(f"build dir: {tmp}")
    ok = True
    open(os.path.join(tmp, "testrsrc.c"), "w").write(DLL_C)
    open(os.path.join(tmp, "testrsrc.def"), "w").write(DLL_DEF)
    open(os.path.join(tmp, "testrsrc.rc"), "w").write(DLL_RC)
    vcrun("rc /nologo /fo testrsrc.res testrsrc.rc", tmp)
    vcrun("cl /nologo /c /O2 /GS- testrsrc.c", tmp)
    vcrun("link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:testrsrc.def "
          "/OUT:testrsrc.dll testrsrc.obj testrsrc.res", tmp)
    dll = os.path.join(tmp, "testrsrc.dll")
    ok = step(os.path.isfile(dll), "built testrsrc.dll with an embedded resource") and ok
    if not os.path.isfile(dll):
        print("\nS7(rsrc) FAIL"); return 1

    pe = PE32.from_file(dll)
    ok = step(any(s.name == ".rsrc" for s in pe.sections), "DLL has a .rsrc section") and ok

    obj = convert(pe, stdcall_args={"Answer": 0})
    obj_path = os.path.join(tmp, "testrsrc_s.obj")
    open(obj_path, "wb").write(obj)
    print(f"      converted obj: {len(obj)} bytes")

    db = find_tool("dumpbin.exe")
    if db:
        heads = subprocess.run([db, "/HEADERS", obj_path], capture_output=True, text=True).stdout
        ok = step(".rsrc" not in heads, "converted obj dropped .rsrc (documented v1 limitation)") and ok

    vcrun("lib /nologo /out:testrsrc_s.lib testrsrc_s.obj", tmp)
    open(os.path.join(tmp, "caller.c"), "w").write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testrsrc_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe), "caller linked") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr); print("\nS7(rsrc) FAIL"); return 1

    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (DLL deleted) exit code",
              f"= {rr.returncode} (want 42: code works, resources skipped)") and ok

    print(f"\n{'='*50}\nS7(rsrc) {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
