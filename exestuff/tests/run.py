#!/usr/bin/env python3
r"""
Regression test (UCL, dynamic CRT): stuff ucl_dll.dll into stufftest.exe as a
CONSOLE exe, remove the DLL, run it, and confirm its stdout is unchanged.
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import exestuff

CORPUS = os.path.join(HERE, "corpus")
EXE = os.path.join(CORPUS, "stufftest.exe")
DLL = os.path.join(CORPUS, "ucl_dll.dll")
OUT = os.path.join(CORPUS, "stufftest_stuffed.exe")
EXPECT = "OK in=2250 comp=64 dec=2250"


def main():
    exestuff.stuff(EXE, DLL, OUT, do_tls=True, do_console=True)

    bak = DLL + ".away"
    os.replace(DLL, bak)                     # prove no DLL at runtime
    try:
        r = subprocess.run([OUT], cwd=CORPUS, capture_output=True, text=True)
        out = (r.stdout or "").strip()
    finally:
        os.replace(bak, DLL)

    print("\n--- stuffed exe output (ucl_dll.dll removed) ---")
    print(out or "(no output)")
    ok = out == EXPECT
    print(f"--- UCL STUFF TEST: {'PASS' if ok else 'FAIL'} ---")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
