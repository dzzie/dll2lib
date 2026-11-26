#!/usr/bin/env python3
"""
S5 test -- reloc conversion on real-world patterns.

One DLL that forces every absolute-reference shape a CRT-built DLL contains:
  * data->code : a const function-pointer table (tbl[]) in .rdata holding the
    addresses of a1/a2/a3 in .text
  * code->data : a1/a2 load volatile globals g1/g2
  * data->data : a const pointer `ps` in .rdata pointing at string `s` in .rdata
  * import     : Msg() calls kernel32!lstrlenA

    int __stdcall Pick(int i, int x) { return tbl[i](x); }
    int __stdcall Msg(void)          { return lstrlenA(ps); }   // 11

Checks (before converting) that the DLL really has data->code and data->data
relocs, then: convert -> lib -> link caller -> delete DLL -> exit 42, where
Pick(0,32)=42, Pick(1,-58)=42, Pick(2,21)=42, Msg()=11.
"""
from __future__ import annotations
import os
import sys
import struct
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
static volatile int g1 = 10, g2 = 100;
static int a1(int x) { return x + g1; }
static int a2(int x) { return x + g2; }
static int a3(int x) { return x * 2; }
static int (*const tbl[3])(int) = { a1, a2, a3 };   /* data -> code */
static const char s[] = "hello world";
static const char *const ps = s;                    /* data -> data */
int __stdcall Pick(int i, int x) { return tbl[i](x); }
int __stdcall Msg(void)          { return lstrlenA(ps); }
"""
DLL_DEF = "LIBRARY testdll5\nEXPORTS\n    Pick\n    Msg\n"
CALLER_C = r"""
__declspec(dllimport) int __stdcall Pick(int i, int x);
__declspec(dllimport) int __stdcall Msg(void);
int main(void) {
    return (Pick(0, 32) == 42 && Pick(1, -58) == 42 &&
            Pick(2, 21) == 42 && Msg() == 11) ? 42 : 1;
}
"""


def step(ok_now, label, detail=""):
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def classify_relocs(pe: PE32):
    """Return a set of (source_section, target_section) pairs across all relocs."""
    def sec_of(rva):
        for s in pe.sections:
            if s.virtual_address <= rva < s.virtual_address + max(s.virtual_size, s.size_of_raw_data):
                return s
        return None
    pairs = set()
    for r in pe.relocs:
        src = sec_of(r.rva)
        if not src or not src.raw:
            continue
        off = r.rva - src.virtual_address
        if off + 4 > len(src.raw):
            continue
        stored = struct.unpack_from("<I", src.raw, off)[0]
        tgt = sec_of((stored - pe.image_base) & 0xFFFFFFFF)
        if tgt:
            pairs.add((src.name, tgt.name))
    return pairs


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s5_")
    print(f"build dir: {tmp}")
    ok = True

    open(os.path.join(tmp, "testdll5.c"), "w").write(DLL_C)
    open(os.path.join(tmp, "testdll5.def"), "w").write(DLL_DEF)
    vcrun("cl /nologo /c /O2 /GS- testdll5.c", tmp)
    vcrun("link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:testdll5.def "
          "kernel32.lib /OUT:testdll5.dll testdll5.obj", tmp)
    dll = os.path.join(tmp, "testdll5.dll")
    ok = step(os.path.isfile(dll), "built testdll5.dll") and ok
    if not os.path.isfile(dll):
        print("\nS5 FAIL"); return 1

    pe = PE32.from_file(dll)
    pairs = classify_relocs(pe)
    print(f"      reloc section pairs (src->tgt): {sorted(pairs)}")
    has_data_to_code = any(t == ".text" and s != ".text" for (s, t) in pairs)
    has_data_to_data = any(s != ".text" and t != ".text" for (s, t) in pairs)
    ok = step(has_data_to_code, "DLL has data->code relocs (fn-ptr table / vtable shape)") and ok
    ok = step(has_data_to_data, "DLL has data->data relocs (pointer-to-data shape)") and ok

    obj = convert(pe, stdcall_args={"Pick": 8, "Msg": 0})
    open(os.path.join(tmp, "testdll5_s.obj"), "wb").write(obj)
    print(f"      converted obj: {len(obj)} bytes")
    vcrun("lib /nologo /out:testdll5_s.lib testdll5_s.obj", tmp)
    ok = step(os.path.isfile(os.path.join(tmp, "testdll5_s.lib")), "lib wrapped -> .lib") and ok

    open(os.path.join(tmp, "caller.c"), "w").write(CALLER_C)
    rc = vcrun("cl /nologo caller.c testdll5_s.lib /Fe:t.exe", tmp)
    exe = os.path.join(tmp, "t.exe")
    ok = step(os.path.isfile(exe), "caller linked against our lib") and ok
    if not os.path.isfile(exe):
        print(rc.stdout + rc.stderr); print("\nS5 FAIL"); return 1

    db = find_tool("dumpbin.exe")
    if db:
        imps = subprocess.run([db, "/IMPORTS", exe], capture_output=True, text=True).stdout
        ok = step("testdll5" not in imps.lower(), "t.exe has NO import on testdll5.dll") and ok

    os.remove(dll)
    rr = subprocess.run([exe])
    ok = step(rr.returncode == 42, "t.exe (DLL deleted) exit code",
              f"= {rr.returncode} (want 42: all fn-ptr + data + import paths correct)") and ok

    print(f"\n{'='*50}\nS5 {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
