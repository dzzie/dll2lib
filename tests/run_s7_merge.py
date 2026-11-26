#!/usr/bin/env python3
"""
S7 (part 2) -- section-merge. A DLL with TWO code sections joined by a
reloc-less rel32 call must be merged into ONE contiguous .text, or the linker
scatters them and the call lands in the wrong place.

    static volatile int g = 40;
    #pragma code_seg(".text2")
    __declspec(noinline) static int addg(int x){ return x + g; }   // in .text2
    #pragma code_seg()
    int __stdcall Cross(int x){ return addg(x); }                  // in .text -> rel32 -> .text2

Cross(2) must be 42 (2 + g=40) only if the cross-section rel32 survives.
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
static volatile int g = 40;
#pragma code_seg(".text2")
__declspec(noinline) static int addg(int x) { return x + g; }
#pragma code_seg()
int __stdcall Cross(int x) { return addg(x); }
"""
DLL_DEF = "LIBRARY testmerge\nEXPORTS\n    Cross\n"
CALLER_C = r"""
__declspec(dllimport) int __stdcall Cross(int x);
int main(void) { return Cross(2) == 42 ? 42 : 1; }
"""


def step(ok_now, label, detail=""):
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def code_section_names(pe):
    return [s.name for s in pe.sections if s.is_code]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s7m_")
    print(f"build dir: {tmp}")
    ok = True
    open(os.path.join(tmp, "testmerge.c"), "w").write(DLL_C)
    open(os.path.join(tmp, "testmerge.def"), "w").write(DLL_DEF)
    vcrun("cl /nologo /c /O2 /GS- testmerge.c", tmp)
    vcrun("link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:testmerge.def "
          "/OUT:testmerge.dll testmerge.obj", tmp)
    dll = os.path.join(tmp, "testmerge.dll")
    ok = step(os.path.isfile(dll), "built testmerge.dll") and ok
    if not os.path.isfile(dll):
        print("\nS7(merge) FAIL"); return 1

    pe = PE32.from_file(dll)
    code = code_section_names(pe)
    ok = step(len(code) >= 2, "DLL has >=2 code sections", f"({code})") and ok

    obj = convert(pe, stdcall_args={"Cross": 4})
    obj_path = os.path.join(tmp, "testmerge_s.obj")
    open(obj_path, "wb").write(obj)
    print(f"      converted obj: {len(obj)} bytes")

    db = find_tool("dumpbin.exe")
    if db:
        heads = subprocess.run([db, "/HEADERS", obj_path], capture_output=True, text=True).stdout
        ok = step(".text2" not in heads, "converted obj has no separate .text2 (merged into .text)") and ok

    vcrun("lib /nologo /out:testmerge_s.lib testmerge_s.obj", tmp)
    open(os.path.join(tmp, "caller.c"), "w").write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testmerge_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe), "caller linked") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr); print("\nS7(merge) FAIL"); return 1

    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (DLL deleted) exit code",
              f"= {rr.returncode} (want 42: cross-section rel32 survived the merge)") and ok

    print(f"\n{'='*50}\nS7(merge) {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
