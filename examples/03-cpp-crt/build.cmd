@echo off
rem Run from an "x86 Native Tools Command Prompt for VS".
setlocal

echo === [1/4] build widget.dll (real C++ DLL, static CRT /MT) ===
cl /nologo /LD /MT /GS /EHsc widget.cpp /link /DEF:widget.def     || exit /b 1

echo.
echo === [2/4] convert widget.dll -^> widget.lib ===
python ..\..\dll2lib.py widget.dll /OUT:widget.lib /DEF:widget.dll2lib.def || exit /b 1

echo.
echo === [3/4] link the caller against widget.lib ===
cl /nologo caller.c widget.lib /Fe:demo.exe                       || exit /b 1

echo.
echo === [4/4] delete widget.dll, then run ===
del widget.dll
.\demo.exe
echo (exit code %errorlevel%)
