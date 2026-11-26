# 02 — a DLL that calls kernel32

Shows **import rebuild**: converting a DLL that itself imports from another DLL.

### Files
- `strlen.c` — the DLL: `MyStrLen(s)` calls `kernel32!lstrlenA(s)`.
- `strlen.def` / `strlen.dll2lib.def` — export + stdcall decoration.
- `caller.c` — calls `MyStrLen("hello world")` and expects `11`.

### Run
```
build.cmd
```

### What it demonstrates
When dll2lib fuses `strlen.dll`, it reconstructs the DLL's import table as
`.idata$2/$3/$4/$5/$6`. After linking, **the host `demo.exe` imports
`kernel32!lstrlenA` directly** — the DLL's dependency became the exe's. Verify
with:

```
dumpbin /imports demo.exe
```

You'll see `KERNEL32.dll` with `lstrlenA`, and no reference to `strlen.dll`
(which is deleted before the run). The program prints
`MyStrLen("hello world") = 11`.
