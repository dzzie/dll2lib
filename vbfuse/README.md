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
- ✓ **UCL** (32 KB, dynamic MSVCRT): `vbfuse UclTest.vbp --fuse ucl_dll.dll`
  fuses it into a standalone exe that compresses/decompresses correctly **with
  the DLL deleted** (`OK src=2250 comp=64 dec=2250`).
- ✓ **SQLite** (`sqlite3_vb6.dll`, 1 MB, **static CRT**, 12,824 relocs): fused
  exe opens an in-memory DB and runs `SELECT 40+2` → 42, **DLL deleted**. The
  static CRT is initialized at load via an injected **TLS callback** (no source
  edit, no C compiler) — see `VB6_FUSION_NOTES.md` §5.
- ✓ **SQLite, full OO classes**: a Standard-EXE app built from the real
  `sqlite4vb` class stack (`cSQLite` / `cSQLiteAPI` / `cSQLiteResults` / … — 45
  Declares) fuses into a 1.1 MB standalone exe that opens `:memory:`, creates a
  table, inserts rows and queries them back (`count=2 row2=fused`) with the DLL
  deleted and **no source change** to the classes.
- ✓ **Fully standalone (`--fuse-runtime`)**: the same app with **both** SQLite
  *and* the VB6 runtime (`msvbvm60.dll`) fused — a single 2.5 MB exe that
  imports only base Windows DLLs (kernel32/user32/gdi32/advapi32/ole32/oleaut32),
  **no `msvbvm60.dll`, no `sqlite3_vb6.dll`** — and still runs the live DB.
  The VB runtime is fused by LinkAlchemy's **VBStatic** (compiled once); vbfuse
  drives it and relinks with `/ENTRY:_VBStaticEntry /NODEFAULTLIB`.

## Usage

```
vbfuse <project.vbp> --fuse foo.dll [--fuse bar.dll ...]
       [--fuse-runtime C:\Windows\SysWOW64\msvbvm60.dll [--vbstatic VBStatic.exe]]
       [--out fused.exe] [--run [-- <args>]]
```

See **`VB6_FUSION_NOTES.md`** for the full VB6 build model, the Declare-thunk
format, the debugger capture, the `/OPT:NOREF` rule, and the TLS-callback CRT-init.

### Tools
`vbcapture.py` (debugger capture) · `vbobj_extern.py` (thunk→extern) ·
`tlsinit.py` (TLS CRT-init object) · `vbfuse.py` (the one command) ·
`trace_build.py` (original investigation probe)

The UCL sample itself (third-party GPL binaries) lives outside this repo under
`vbleg/`; these tools take paths as arguments.
