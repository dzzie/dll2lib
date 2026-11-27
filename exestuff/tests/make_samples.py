#!/usr/bin/env python3
r"""
Generate the committed "stuffed" sample binaries for analysis (e.g. vbdec):
for each corpus target, a native-compiled stuffed build and a P-code-compiled
stuffed build (`_p`). Needs VB6 (to compile the P-code variants).

    <name>_stuffed.exe   / <name>_stuffed_p.exe     (exe targets)
    sqlite4vb_stuffed.dll / sqlite4vb_stuffed_p.dll  (ActiveX DLL target)

The native builds match what the regression tests produce (so running the tests
doesn't dirty them); the `_p` builds are P-code compiles of the same projects.
"""
import os
import re
import sys
import glob
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import exestuff

VB6 = r"C:\Program Files (x86)\Microsoft Visual Studio\VB98\VB6.EXE"

# (corpus dir, .vbp, C DLL to fuse, output base name, is a DLL target?)
TARGETS = [
    ("corpus",         "stufftest.vbp",     "ucl_dll.dll",     "stufftest",     False),
    ("corpus_sql",     "stufftest_sql.vbp", "sqlite3_vb6.dll", "stufftest_sql", False),
    ("corpus_activex", "sqlite4vb.vbp",     "sqlite3_vb6.dll", "sqlite4vb",     True),
]


def compile_pcode(corpus, vbp, ext):
    """Recompile the project as P-code to a temp dir; return the built file."""
    vbp_path = os.path.join(corpus, vbp)
    orig = open(vbp_path, "r", encoding="latin-1", newline="").read()
    patched = re.sub(r"CompilationType=-?\d+", "CompilationType=-1", orig, count=1)
    tmp = tempfile.mkdtemp()
    try:
        open(vbp_path, "w", encoding="latin-1", newline="").write(patched)
        subprocess.run([VB6, "/make", vbp_path, "/out", os.path.join(tmp, "log.txt"),
                        "/outdir", tmp], capture_output=True)
    finally:
        open(vbp_path, "w", encoding="latin-1", newline="").write(orig)   # restore native
    hits = glob.glob(os.path.join(tmp, "*." + ext))
    if not hits:
        raise SystemExit(f"P-code compile produced no .{ext} for {vbp}")
    return hits[0]


def main():
    for corpus, vbp, cdll, base, is_dll in TARGETS:
        cdir = os.path.join(HERE, corpus)
        ext = "dll" if is_dll else "exe"
        console = not is_dll
        native = os.path.join(cdir, base + "." + ext)
        cdllp = os.path.join(cdir, cdll)

        exestuff.stuff(native, cdllp, os.path.join(cdir, base + "_stuffed." + ext),
                       do_tls=True, do_console=console)
        pcode = compile_pcode(cdir, vbp, ext)
        exestuff.stuff(pcode, cdllp, os.path.join(cdir, base + "_stuffed_p." + ext),
                       do_tls=True, do_console=console)
        print(f"  {base}: native + P-code stuffed ({ext})")
    print("samples generated.")


if __name__ == "__main__":
    raise SystemExit(main())
