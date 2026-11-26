"""
msvc.py  -  locate and invoke the MS x86 build tools (cl/link/lib/dumpbin).

PE32/i386 output needs the x86 toolset; we run tools inside the vcvars32
environment. Invocation uses shell=True with a command STRING: passing a list
routes through list2cmdline, which escapes the quotes around the vcvars path
as \" and cmd rejects it.
"""
from __future__ import annotations
import glob
import subprocess

_VS = [r"C:\Program Files (x86)\Microsoft Visual Studio\2022",
       r"C:\Program Files\Microsoft Visual Studio\2022"]


def find_vcvars32() -> str:
    for base in _VS:
        hits = sorted(glob.glob(base + r"\*\VC\Auxiliary\Build\vcvars32.bat"))
        if hits:
            return hits[-1]
    raise RuntimeError("vcvars32.bat (x86 build tools) not found")


def find_tool(name: str) -> str:
    for base in _VS:
        hits = sorted(glob.glob(base + rf"\*\VC\Tools\MSVC\*\bin\Host*\x64\{name}"))
        if hits:
            return hits[-1]
    return ""


def vcrun(cmd: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    bat = f'call "{find_vcvars32()}" >nul 2>&1 && {cmd}'
    return subprocess.run(bat, cwd=cwd, shell=True, capture_output=True, text=True)
