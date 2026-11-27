#!/usr/bin/env python3
r"""
Relocatable-target regression (ActiveX DLL): stuff sqlite3_vb6.dll into the
sqlite4vb ActiveX DLL (Type=OleDll, has a .reloc / ASLR), register it, remove the
C DLL, and drive it over COM via a 32-bit host -- confirming the fused engine runs
standalone AND the process exits cleanly (the FLS-callback teardown fix).

Needs 32-bit Python (to register/load the 32-bit in-proc DLL) on Windows.
"""
import os
import sys
import struct
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import exestuff

CORPUS = os.path.join(HERE, "corpus_activex")
AX = os.path.join(CORPUS, "sqlite4vb.dll")          # the ActiveX DLL (target)
CDLL = os.path.join(CORPUS, "sqlite3_vb6.dll")      # the C DLL to stuff
OUT = os.path.join(CORPUS, "sqlite4vb_stuffed.dll")
CSCRIPT32 = r"C:\Windows\SysWOW64\cscript.exe"      # 32-bit host for a 32-bit inproc
EXPECT = "version=3.53.0\ncount=2\nrow2=fused"

VBS = (
    'Dim o : Set o = CreateObject("SqlLite4VB.cSQLite")\n'
    'WScript.Echo "version=" & o.Version\n'
    'o.OpenDB ":memory:"\n'
    'o.Execute "CREATE TABLE t(id INTEGER PRIMARY KEY, body TEXT)"\n'
    'o.Execute "INSERT INTO t(body) VALUES(\'hello\'),(\'fused\')"\n'
    'WScript.Echo "count=" & o.Scalar("SELECT COUNT(*) FROM t")\n'
    'WScript.Echo "row2=" & o.Scalar("SELECT body FROM t WHERE id=2")\n'
)


def _regsvr(path, unregister=False):
    import ctypes
    h = ctypes.WinDLL(path)
    fn = h.DllUnregisterServer if unregister else h.DllRegisterServer
    fn.restype = ctypes.c_long
    return fn() & 0xFFFFFFFF


def main():
    if struct.calcsize("P") != 4:
        print("SKIP: 32-bit Python required to register/load the 32-bit ActiveX DLL")
        return 0

    exestuff.stuff(AX, CDLL, OUT, do_tls=True)       # stuff (reloc path + TLS)

    hr = _regsvr(OUT)                                # per-user COM registration
    if hr != 0:
        print("DllRegisterServer failed hr=0x%X" % hr)
        return 1

    vbs = os.path.join(CORPUS, "_axtest.vbs")
    open(vbs, "w").write(VBS)
    bak = CDLL + ".away"
    os.replace(CDLL, bak)                            # prove no C DLL at runtime
    try:
        r = subprocess.run([CSCRIPT32, "//nologo", vbs], capture_output=True, text=True)
        out = (r.stdout or "").replace("\r\n", "\n").strip()
        code = r.returncode & 0xFFFFFFFF
    finally:
        os.replace(bak, CDLL)
        _regsvr(OUT, unregister=True)
        try:
            os.remove(vbs)
        except OSError:
            pass

    print("\n--- stuffed ActiveX DLL via COM (sqlite3_vb6.dll removed) ---")
    print(out or "(no output)")
    clean = (code == 0)                              # clean teardown (FLS fix)
    ok = (out == EXPECT) and clean
    print("--- ACTIVEX STUFF TEST: %s  (cscript exit 0x%X) ---"
          % ("PASS" if ok else "FAIL", code))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
