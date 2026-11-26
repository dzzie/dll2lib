@echo off
rem Run from an "x86 Native Tools Command Prompt for VS".
setlocal

echo === [1/4] build strlen.dll (imports kernel32!lstrlenA) ===
cl /nologo /c /O2 /GS- strlen.c                                                              || exit /b 1
link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:strlen.def kernel32.lib /OUT:strlen.dll strlen.obj || exit /b 1

echo.
echo === [2/4] convert strlen.dll -^> strlen.lib (rebuilds the import table) ===
python ..\..\dll2lib.py strlen.dll /OUT:strlen.lib /DEF:strlen.dll2lib.def                   || exit /b 1

echo.
echo === [3/4] link the caller against strlen.lib ===
cl /nologo caller.c strlen.lib /Fe:demo.exe                                                  || exit /b 1

echo.
echo === [4/4] delete strlen.dll, then run ===
del strlen.dll
echo (demo.exe now depends on kernel32 directly -- see: dumpbin /imports demo.exe)
.\demo.exe
echo (exit code %errorlevel%)
