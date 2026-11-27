@echo off
rem Run from an "x86 Native Tools Command Prompt for VS".
setlocal

echo === [1/4] build widgetlib.dll (real C++ DLL, static CRT /MT, from widget.cpp) ===
cl /nologo /LD /MT /GS /EHsc widget.cpp /Fe:widgetlib.dll /link /DEF:widget.def   || exit /b 1

echo.
echo === [2/4] convert widgetlib.dll -^> widgetlib.lib ===
python ..\..\dll2lib.py widgetlib.dll /OUT:widgetlib.lib /DEF:widget.dll2lib.def || exit /b 1

echo.
echo === [3/4] link the caller against widgetlib.lib ===
cl /nologo caller.c widgetlib.lib /Fe:demo.exe                                    || exit /b 1

echo.
echo === [4/4] delete widgetlib.dll, then run ===
del widgetlib.dll
.\demo.exe
echo (exit code %errorlevel%)
