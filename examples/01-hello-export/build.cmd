@echo off
rem Run from an "x86 Native Tools Command Prompt for VS".
setlocal

echo === [1/4] build hello.dll (an ordinary DLL) ===
cl /nologo /c /O2 /GS- hello.c                                                   || exit /b 1
link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:hello.def /OUT:hello.dll hello.obj  || exit /b 1

echo.
echo === [2/4] convert hello.dll -^> hello.lib (static) ===
python ..\..\dll2lib.py hello.dll /OUT:hello.lib /DEF:hello.dll2lib.def           || exit /b 1

echo.
echo === [3/4] link the caller against hello.lib ===
cl /nologo caller.c hello.lib /Fe:demo.exe                                        || exit /b 1

echo.
echo === [4/4] delete hello.dll, then run (no DLL at runtime) ===
del hello.dll
.\demo.exe
echo (exit code %errorlevel%)
