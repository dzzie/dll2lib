@echo off
rem Build the UCL fusion demo. Run from an "x86 Native Tools Command Prompt for VS"
rem (so cl/link/lib are on PATH) with VB6 installed. Pass --run to run it after.
python "%~dp0build.py" %*
