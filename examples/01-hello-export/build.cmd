@echo off
rem Run from an "x86 Native Tools Command Prompt for VS".
setlocal

echo === [1/4] build hellolib.dll (an ordinary DLL, compiled from hello.c) ===
cl /nologo /c /O2 /GS- hello.c                                                       || exit /b 1
link /nologo /DLL /NODEFAULTLIB /NOENTRY /DEF:hello.def /OUT:hellolib.dll hello.obj   || exit /b 1

echo.
echo === [2/4] convert hellolib.dll -^> hellolib.lib (static, via dll2lib) ===
python ..\..\dll2lib.py hellolib.dll /OUT:hellolib.lib /DEF:hello.dll2lib.def       || exit /b 1

echo.
echo === [3/4] link the caller against hellolib.lib ===
cl /nologo caller.c hellolib.lib /Fe:demo.exe                                         || exit /b 1

echo.
echo === [4/4] delete hellolib.dll, then run (no DLL at runtime) ===
del hellolib.dll
.\demo.exe
echo (exit code %errorlevel%)
