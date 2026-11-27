@echo off
rem Run from an "x86 Native Tools Command Prompt for VS".
setlocal

echo === [1/4] build strlenlib.dll (imports kernel32!lstrlenA, from strlen.c) ===
cl /nologo /c /O2 /GS- strlen.c                                                                     || exit /b 1
link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:strlen.def kernel32.lib /OUT:strlenlib.dll strlen.obj || exit /b 1

echo.
echo === [2/4] convert strlenlib.dll -^> strlenlib.lib (rebuilds the import table) ===
python ..\..\dll2lib.py strlenlib.dll /OUT:strlenlib.lib /DEF:strlen.dll2lib.def                  || exit /b 1

echo.
echo === [3/4] link the caller against strlenlib.lib ===
cl /nologo caller.c strlenlib.lib /Fe:demo.exe                                                      || exit /b 1

echo.
echo === [4/4] delete strlenlib.dll, then run ===
del strlenlib.dll
echo (demo.exe now depends on kernel32 directly -- see: dumpbin /imports demo.exe)
.\demo.exe
echo (exit code %errorlevel%)
