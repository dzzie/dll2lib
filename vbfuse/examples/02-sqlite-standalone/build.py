#!/usr/bin/env python3
"""
Build the fully-standalone SQLite demo.

Fuses BOTH the SQLite engine (`sqlite3_vb6.dll`) AND the VB6 runtime
(`msvbvm60.dll`, via VBStatic) into the VB6 app `SqlApp`, producing
`sqlapp_fused.exe` that imports only base Windows DLLs -- no sqlite3_vb6.dll,
no msvbvm60.dll -- and runs a live in-memory database.

Requires VB6 (VB98) + MS Build Tools (x86). VBStatic.exe is bundled here
(built from VB6-LinkAlchemy by UltraAlex0, MIT -- see README).
    python build.py          # build only
    python build.py --run    # build, then run and write result.txt
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VBFUSE = os.path.normpath(os.path.join(HERE, "..", "..", "vbfuse.py"))
MSVBVM = r"C:\Windows\SysWOW64\msvbvm60.dll"

cmd = [sys.executable, VBFUSE, os.path.join(HERE, "SqlApp.vbp"),
       "--fuse", os.path.join(HERE, "sqlite3_vb6.dll"),
       "--fuse-runtime", MSVBVM,
       "--vbstatic", os.path.join(HERE, "VBStatic.exe"),
       "--out", os.path.join(HERE, "sqlapp_fused.exe")]
if "--run" in sys.argv:
    cmd += ["--run", "--", os.path.join(HERE, "result.txt")]
raise SystemExit(subprocess.call(cmd))
