@echo off
rem Build the fully-standalone SQLite demo. Run from an "x86 Native Tools Command
rem Prompt for VS" with VB6 installed. Pass --run to run it after.
python "%~dp0build.py" %*
