# vbfuse — fuse a C DLL into a compiled VB6 program

Goal: take a VB6 project that calls a C DLL via `Declare Function ... Lib
"foo.dll"` and produce a standalone `.exe` with that DLL's code **fused in** —
no `foo.dll` at runtime — **without editing the VB source, swapping VB6's
`LINK.EXE`, or installing any add-in.**

## Why it's not just dll2lib

A VB6 `Declare Lib "foo.dll"` does **not** create an import — `msvbvm60`'s
`DllFunctionCall` does `LoadLibrary`/`GetProcAddress` at runtime. VB6/C2 compiles
each `Declare` into a 25-byte thunk in the **project `.OBJ`**. So fusion needs
two moves: rewrite those thunks into ordinary linker externs, then satisfy them
with a static lib built from the C DLL.

## Pipeline (on-demand, zero footprint)

```
1. run  VB6.EXE /make  under a Win32 debugger            (trace_build.py)
2. at the LINK.EXE spawn: copy the OBJs + save the exact link command line
3. vbobj_extern  <project>.OBJ  --placeholder:foo.dll     (Declare thunks -> externs)
4. dll2lib       foo.dll -> foo.lib                       (full static conversion)
5. relink with VB98\LINK.EXE: captured args + patched OBJ + foo.lib -> fused .exe
```

Nothing is installed or permanently changed; VB6 compiles normally and the
"magic" happens transiently in the launcher.

## Tools

| File | Role |
|---|---|
| `trace_build.py` | debugger launcher: runs VB6 `/make`, captures OBJs + link cmd at the LINK spawn (VB6 deletes OBJs after, so capture-at-spawn is essential) |
| `vbobj_extern.py` | port of VB6-LinkAlchemy's VBExtern: rewrites `Declare` thunks whose Lib name matches `--placeholder` into undefined linker externs (`_Func`), reusing the thunk's own reloc so nothing grows. `--list` to inspect. |
| *(dll2lib)* | the parent project converts the C DLL to the static `.lib` the externs resolve against |

## Status

- ✓ **Investigation**: mapped VB6 `/make` (C2.EXE per module → OBJ; LINK.EXE;
  OBJs deleted after). `trace_build.py` captures OBJs + the link line.
- ✓ **vbobj_extern**: validated on a real captured `vbTest.OBJ` — finds the 5
  `ucl_dll.dll` Declares, rewrites the thunks to `jmp _Func` + int3 padding,
  appends the externs (dumpbin confirms).
- ✓ **Relink connects**: VB6's `LINK.EXE` resolves every extern against a
  dll2lib-built `ucl_dll.lib` with no unresolved symbols.
- ⧖ **Next**: a headless Sub-Main harness that actually calls the functions
  (so dead-strip keeps them and the result is file-checkable), then wrap the
  whole flow as a single `vbfuse` command.

The UCL sample itself (third-party GPL binaries) lives outside this repo under
`vbleg/`; these tools take paths as arguments.
