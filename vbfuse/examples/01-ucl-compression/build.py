#!/usr/bin/env python3
"""
Build the UCL fusion demo.

Fuses the C compression DLL `ucl_dll.dll` into the VB6 app `UclTest`, producing
`ucltest_fused.exe` which compresses/decompresses with NO ucl_dll.dll at runtime.

Requires VB6 (VB98) + MS Build Tools (x86) on this machine.
    python build.py          # build only
    python build.py --run    # build, then run and write result.txt
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VBFUSE = os.path.normpath(os.path.join(HERE, "..", "..", "vbfuse.py"))

cmd = [sys.executable, VBFUSE, os.path.join(HERE, "UclTest.vbp"),
       "--fuse", os.path.join(HERE, "ucl_dll.dll"),
       "--out", os.path.join(HERE, "ucltest_fused.exe")]
if "--run" in sys.argv:
    cmd += ["--run", "--", os.path.join(HERE, "result.txt")]
raise SystemExit(subprocess.call(cmd))
