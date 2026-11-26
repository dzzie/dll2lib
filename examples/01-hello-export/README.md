# 01 — hello export

The simplest case: a DLL with a single `__stdcall` export that reads a global,
fused into an executable.

### Files
- `hello.c` — the DLL: `AddNumbers(a, b)` returns `a + b + g_bias` (`g_bias`
  is a global, so the DLL has a real base relocation to convert).
- `hello.def` — exports `AddNumbers` (used to build the DLL).
- `hello.dll2lib.def` — tells dll2lib the stdcall decoration (`_AddNumbers@8`).
- `caller.c` — calls `AddNumbers(20, 22)` and expects `142`.

### Run
```
build.cmd
```

### What it demonstrates
- `dll2lib hello.dll /OUT:hello.lib /DEF:hello.dll2lib.def` turns the DLL into a
  static library.
- The caller links `hello.lib` and calls the export.
- `hello.dll` is **deleted** before running — the program still prints
  `AddNumbers(20, 22) = 142`, proving the code was fused in (the `+ 100`
  confirms the `g_bias` relocation was converted correctly).

This DLL has no `DllMain`/CRT, so no `StaticInit` call is needed
(see example 03 for that).
