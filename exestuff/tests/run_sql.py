#!/usr/bin/env python3
r"""
Static-CRT regression (SQLite): stuff sqlite3_vb6.dll (1 MB, static CRT, 45
exports) into stufftest_sql.exe as a CONSOLE exe, remove the DLL, run it, and
confirm the fused engine still queries an in-memory DB. Exercises the injected
TLS callback (DllMainCRTStartup) so the static CRT heap / malloc work.
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import exestuff

CORPUS = os.path.join(HERE, "corpus_sql")
EXE = os.path.join(CORPUS, "stufftest_sql.exe")
DLL = os.path.join(CORPUS, "sqlite3_vb6.dll")
OUT = os.path.join(CORPUS, "stufftest_sql_stuffed.exe")
EXPECT = "OK version=3.53.0 count=2 row2=fused"


def main():
    exestuff.stuff(EXE, DLL, OUT, do_tls=True, do_console=True)

    bak = DLL + ".away"
    os.replace(DLL, bak)
    try:
        r = subprocess.run([OUT], cwd=CORPUS, capture_output=True, text=True)
        out = (r.stdout or "").strip()
    finally:
        os.replace(bak, DLL)

    print("\n--- stuffed exe output (sqlite3_vb6.dll removed) ---")
    print(out or "(no output)")
    ok = out == EXPECT
    print(f"--- SQLITE STUFF TEST: {'PASS' if ok else 'FAIL'} ---")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
