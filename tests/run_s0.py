#!/usr/bin/env python3
"""
S0 test: validate the hand-rolled PE32 reader against dumpbin (the oracle)
on several real 32-bit system DLLs. Green = our parse agrees with dumpbin on
section layout, image base, entry point, alignments, exported-name count,
imported-DLL set, and HIGHLOW reloc count.

Run from anywhere:  python tests/run_s0.py
Exit 0 iff every field matches on every DLL.
"""
from __future__ import annotations
import os
import re
import sys
import glob
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from pe32 import PE32  # noqa: E402

SYSWOW = r"C:\Windows\SysWOW64"
CANDIDATES = ["version.dll", "kernel32.dll", "user32.dll", "advapi32.dll",
              "gdi32.dll", "shlwapi.dll", "msvbvm60.dll", "winmm.dll"]


def find_dumpbin() -> str:
    pats = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\2022\*\VC\Tools\MSVC\*\bin\Host*\x64\dumpbin.exe",
        r"C:\Program Files\Microsoft Visual Studio\2022\*\VC\Tools\MSVC\*\bin\Host*\x64\dumpbin.exe",
    ]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    raise SystemExit("could not locate dumpbin.exe")


def run_dumpbin(db: str, path: str) -> str:
    r = subprocess.run([db, "/HEADERS", "/EXPORTS", "/IMPORTS", "/RELOCATIONS", path],
                       capture_output=True, text=True)
    return r.stdout


# ---- oracle extractors ----
def _hex1(pat: str, text: str):
    m = re.search(pat, text)
    return int(m.group(1), 16) if m else None


def oracle_facts(text: str) -> dict:
    f = {}
    f["machine"] = _hex1(r"([0-9A-Fa-f]+) machine ", text)
    f["image_base"] = _hex1(r"([0-9A-Fa-f]+) image base", text)
    f["entry"] = _hex1(r"([0-9A-Fa-f]+) entry point", text)
    f["sec_align"] = _hex1(r"([0-9A-Fa-f]+) section alignment", text)
    f["file_align"] = _hex1(r"([0-9A-Fa-f]+) file alignment", text)
    # section names, in order
    f["sections"] = re.findall(r"SECTION HEADER #[0-9A-F]+\s*\n\s*(\S+) name", text)
    # exported names count (dumpbin prints this in DECIMAL)
    m = re.search(r"(\d+) number of names", text)
    f["n_names"] = int(m.group(1), 10) if m else None
    # imported DLLs -- scope to the NORMAL import table only (dumpbin also
    # dumps the delay-load table, which we compare separately)
    f["imports"] = _dll_set(text, delay=False)
    f["delay"] = _dll_set(text, delay=True)
    # HIGHLOW reloc count
    f["highlow"] = len(re.findall(r"HIGHLOW", text))
    return f


def _dll_set(text: str, delay: bool) -> set[str]:
    # dumpbin emits the delay-load section and the normal section in either
    # order; bound each body at the NEXT "Section contains" header or Summary.
    hdr = "following delay load imports:" if delay else "following imports:"
    m = re.search(re.escape(hdr) + r"(.*?)(?=Section contains the following|\n\s*Summary|\Z)",
                  text, re.S)
    body = m.group(1) if m else ""
    return {s.lower() for s in re.findall(r"(?mi)^    ([A-Za-z0-9_.\-]+\.dll)\s*$", body)}


def ours_facts(pe: PE32) -> dict:
    return {
        "machine": pe.machine,
        "image_base": pe.image_base,
        "entry": pe.address_of_entry_point,
        "sec_align": pe.section_alignment,
        "file_align": pe.file_alignment,
        "sections": [s.name for s in pe.sections],
        "n_names": len([e for e in pe.exports if e.name]),
        "imports": {i.name.lower() for i in pe.imports},
        "delay": {d.name.lower() for d in pe.delay_imports},
        "highlow": pe.reloc_type_counts.get(3, 0),
    }


FIELDS = ["machine", "image_base", "entry", "sec_align", "file_align",
          "sections", "n_names", "imports", "delay", "highlow"]


def cmp_dll(db: str, path: str) -> bool:
    pe = PE32.from_file(path)
    text = run_dumpbin(db, path)
    o = oracle_facts(text)
    a = ours_facts(pe)
    ok = True
    print(f"\n=== {os.path.basename(path)} ===")
    for k in FIELDS:
        ov, av = o.get(k), a.get(k)
        if ov is None:
            print(f"  [skip] {k}: dumpbin gave no value")
            continue
        if k in ("imports", "delay"):
            match = (ov == av)
            extra = f"(ours {len(av)}, dumpbin {len(ov)})"
            if not match:
                extra += f"  only-ours={sorted(av - ov)} only-db={sorted(ov - av)}"
        elif k == "sections":
            match = (ov == av)
            extra = f"{av}" if match else f"ours={av} db={ov}"
        else:
            match = (ov == av)
            extra = f"0x{av:X}" if isinstance(av, int) else str(av)
            if not match:
                extra = f"ours={av!r} db={ov!r}"
        print(f"  [{'OK ' if match else 'XX '}] {k:<11}: {extra}")
        ok = ok and match
    return ok


def main() -> int:
    db = find_dumpbin()
    print(f"dumpbin: {db}")
    dlls = [os.path.join(SYSWOW, c) for c in CANDIDATES
            if os.path.isfile(os.path.join(SYSWOW, c))]
    if not dlls:
        raise SystemExit("no test DLLs found in SysWOW64")
    all_ok = True
    tested = 0
    for path in dlls:
        try:
            ok = cmp_dll(db, path)
        except Exception as e:
            print(f"\n=== {os.path.basename(path)} ===\n  EXCEPTION: {e!r}")
            ok = False
        all_ok = all_ok and ok
        tested += 1
    print(f"\n{'='*50}\nS0 {'PASS' if all_ok else 'FAIL'} ({tested} DLLs tested)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
