#!/usr/bin/env python3
"""
S1 test: the hand-rolled COFF writer emits an object that MS lib.exe wraps and
MS link.exe consumes and runs correctly.

We build (by hand, via coff.py) a trivial i386 object:

    .text   _answer:            mov  eax, [_the_answer_value]   ; A1 <DIR32>
                                ret                             ; C3
    .data   _the_answer_value:  dd 42

This exercises: two sections, a DIR32 relocation, an external code symbol, an
external data symbol, a long (>8 char) symbol name (-> string table). Then:
  lib  -> ans.lib
  cl   -> compiles a C caller `int main(){ return answer(); }`
  link -> t.exe
  run  -> must exit 42.

Exit 0 iff the whole chain is green.
"""
from __future__ import annotations
import os
import sys
import glob
import struct
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from coff import (CoffBuilder, FLAGS_TEXT, FLAGS_DATA,  # noqa: E402
                  REL_DIR32, SYM_TYPE_FUNCTION)


def find_vcvars32() -> str:
    pats = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\2022\*\VC\Auxiliary\Build\vcvars32.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\*\VC\Auxiliary\Build\vcvars32.bat",
    ]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    raise SystemExit("could not locate vcvars32.bat (x86 tools)")


def find_dumpbin() -> str:
    hits = sorted(glob.glob(
        r"C:\Program Files*\Microsoft Visual Studio\2022\*\VC\Tools\MSVC\*\bin\Host*\x64\dumpbin.exe"))
    return hits[-1] if hits else ""


VCVARS32 = find_vcvars32()


def vcrun(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    # shell=True (string, not list): a list would route through list2cmdline,
    # which escapes the quotes around the vcvars path as \" and cmd rejects it.
    bat = f'call "{VCVARS32}" >nul 2>&1 && {cmd}'
    return subprocess.run(bat, cwd=cwd, shell=True, capture_output=True, text=True)


def build_obj() -> bytes:
    cb = CoffBuilder()
    text = cb.add_section(".text", FLAGS_TEXT)
    data = cb.add_section(".data", FLAGS_DATA)
    text.append(bytes([0xA1, 0, 0, 0, 0, 0xC3]))     # mov eax,[abs32]; ret
    data.append(struct.pack("<I", 42))                # the value
    val = cb.define("_the_answer_value", 0, data.number)   # long name -> string table
    cb.define("_answer", 0, text.number, typ=SYM_TYPE_FUNCTION)
    cb.reloc(text, 1, val, REL_DIR32)                 # fix the abs32 operand
    return cb.build()


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s1_")
    print(f"build dir: {tmp}")
    ok = True

    obj = build_obj()
    obj_path = os.path.join(tmp, "ans.obj")
    with open(obj_path, "wb") as f:
        f.write(obj)
    print(f"wrote {obj_path} ({len(obj)} bytes)")

    # sanity: dumpbin must parse our obj and see the symbols + the DIR32 reloc
    db = find_dumpbin()
    if db:
        r = subprocess.run([db, "/SYMBOLS", "/RELOCATIONS", obj_path],
                           capture_output=True, text=True)
        out = r.stdout
        for needle in ("_answer", "_the_answer_value", "DIR32"):
            present = needle in out
            print(f"  [{'OK ' if present else 'XX '}] dumpbin sees {needle!r}")
            ok = ok and present
    else:
        print("  [skip] dumpbin not found")

    # lib.exe wraps our obj
    r = vcrun("lib /nologo /out:ans.lib ans.obj", tmp)
    lib_ok = (r.returncode == 0 and os.path.isfile(os.path.join(tmp, "ans.lib")))
    print(f"  [{'OK ' if lib_ok else 'XX '}] lib.exe wrapped ans.obj -> ans.lib")
    if not lib_ok:
        print(r.stdout + r.stderr)
    ok = ok and lib_ok

    # C caller, compiled + linked against our lib
    with open(os.path.join(tmp, "main.c"), "w") as f:
        f.write("extern int answer(void);\nint main(void){ return answer(); }\n")
    r = vcrun("cl /nologo main.c ans.lib /Fe:t.exe", tmp)
    link_ok = (r.returncode == 0 and os.path.isfile(os.path.join(tmp, "t.exe")))
    print(f"  [{'OK ' if link_ok else 'XX '}] cl+link produced t.exe")
    if not link_ok:
        print(r.stdout + r.stderr)
    ok = ok and link_ok

    # run it -- must return 42
    if link_ok:
        rr = subprocess.run([os.path.join(tmp, "t.exe")])
        run_ok = (rr.returncode == 42)
        print(f"  [{'OK ' if run_ok else 'XX '}] t.exe exit code = {rr.returncode} (want 42)")
        ok = ok and run_ok

    print(f"\n{'='*50}\nS1 {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
