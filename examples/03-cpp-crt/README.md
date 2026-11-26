# 03 — real C++ DLL with CRT + DllMain (the bootstrap)

A normal `/MT` C++ DLL — static CRT, a C++ global constructor, and a `DllMain`.
This is what a DLL you'd actually ship looks like, and it shows why the
**`StaticInit` bootstrap** exists.

### Files
- `widget.cpp` — a global ctor sets `g_value = 40`; `DllMain` adds `2` on
  attach; `GetWidget()` returns `g_value`.
- `widget.def` / `widget.dll2lib.def` — export + stdcall decoration.
- `caller.c` — prints `GetWidget()` **before and after** calling
  `widget_StaticInit()`.

### Run
```
build.cmd
```

### What it demonstrates
Neither the C++ constructor nor `DllMain` runs on its own in a fused build —
they run inside the DLL's CRT entry (`DllMainCRTStartup`). dll2lib emits
`widget_StaticInit()`, which invokes that entry with `DLL_PROCESS_ATTACH`.

Expected output:
```
before StaticInit: GetWidget() = 0  (expected 0)
after  StaticInit: GetWidget() = 42  (expected 42)
```

`0 -> 42` proves the whole CRT startup (global ctor **40** + `DllMain` **+2**)
ran through the bootstrap. **Contract:** call `<dll>_StaticInit()` exactly once,
before using any export.
