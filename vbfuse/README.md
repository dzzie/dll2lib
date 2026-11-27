# vbfuse — fuse a C DLL into a compiled VB6 program

> **Built on [VB6‑LinkAlchemy](https://github.com/ultraalex00/VB6-LinkAlchemy) by
> UltraAlex0.** That project pioneered embedding `MSVBVM60.DLL` into a VB6
> EXE/DLL and is the direct inspiration and foundation for this whole leg.
> `vbfuse --fuse-runtime` drives its **VBStatic** to fuse the VB6 runtime, and
> `vbobj_extern.py` is a Python port of its **VBExtern**. Huge thanks.
> Write‑up: https://www.vbforums.com/showthread.php?912383-VB6-LinkAlchemy-Embedding-MSVBVM60-DLL-into-EXE-DLL

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
       [--console] [--out fused.exe] [--run [-- <args>]]
```

### Naming the fused code

Once a DLL is fused, its functions are just anonymous bytes in the exe. vbfuse
re-emits every fused export in the exe's own export table (export name → fused
RVA), so `dumpbin /exports` / IDA can name them:

```
> dumpbin /exports ucltest_fused.exe
      1    0 00003295 Compress
      2    1 000032FA DeCompress
      3    2 00003251 Init
      ...
```

No runtime effect — it only adds a read-only export directory. Two VC6-`LINK`
quirks make it work: the export must be a **plain** name so the linker runs its
own decoration search onto dll2lib's `_Name`, and the fused object is linked
**directly** rather than as a `.lib` so even *unused* exports are present when the
export table is built.

### Testing with `--console`

`--console` builds the fused exe with the **CONSOLE** subsystem, so a VB app can
write straight to stdout (easy to capture in a test harness). Add a tiny print
helper to your `Sub Main` project — e.g. wqweto's one-liner:

```vb
Public Sub ConsolePrint(sText As String)
    Static oStdOut As Object
    If oStdOut Is Nothing Then _
        Set oStdOut = CreateObject("Scripting.FileSystemObject").GetStandardStream(1)
    oStdOut.Write sText
End Sub
```

Then `vbfuse app.vbp --fuse foo.dll --console --run` prints the app's output to
the console. (For full console I/O — argv, stdin, pipes, exit codes — see Karl E.
Peterson's classic `MConsole.bas`.)

### Fusing the VB6 runtime (`--fuse-runtime`)

A plain `--fuse foo.dll` build is entirely our own code. But `--fuse-runtime` —
which also embeds `msvbvm60.dll` for a *fully* standalone exe — is done by
**UltraAlex0's compiled `VBStatic.exe`** (from VB6‑LinkAlchemy). vbfuse runs it
as a subprocess on the **captured main project `.OBJ`**
(`VBStatic.exe msvbvm60.dll <main>.OBJ`): it merges the runtime into that OBJ and
defines `_VBStaticEntry`, then vbfuse relinks. We ported the *Declare‑thunk
rewrite* to Python (`vbobj_extern.py`), but the runtime‑fusion itself is his tool
— credited, not rewritten.

So **`--fuse-runtime` requires `VBStatic.exe` on disk** (bundled at the repo's
`tools/VBStatic.exe`; `find_vbstatic()` locates it automatically, or pass
`--vbstatic <path>`). Plain C‑DLL fusion needs none of this.

Because VBStatic (and the relink) operate on the captured OBJs, timing matters:
VB6 deletes the OBJs the instant its own link finishes, so `vbcapture` grabs them
mid‑build at the `LINK.EXE` spawn into `vbfuse_work/obj/`. That work dir is
**kept, not cleaned** — handy for inspecting exactly what went into the fuse;
remove it with `rm -rf vbfuse_work` when done.

See **`VB6_FUSION_NOTES.md`** for the full VB6 build model, the Declare-thunk
format, the debugger capture, the `/OPT:NOREF` rule, and the TLS-callback CRT-init.

## Limitations

vbfuse inherits **every** dll2lib limitation (see the top-level
[README → Limitations](../README.md#limitations)) and adds a few of its own:

- **x86 (32-bit) only, and toolchain-dependent.** It drives the real `VB6.EXE`
  (VB98) and VB6's own `LINK.EXE`, so both **VB6** and the **x86 MS Build Tools**
  must be installed. It's a Windows-only, on-your-machine build step.
- **Each fused C DLL must be dll2lib-convertible** — no x64, no bound or
  delay-load imports, no own TLS directory; `.rsrc` is dropped; CRT init runs
  under loader lock. Check first with `dll2lib foo.dll /DUMP`.
- **Only `Declare`-reached DLLs are fused.** vbfuse targets DLLs called via
  `Declare Lib "foo.dll"`. A dependency reached another way is **not** fused: a
  C DLL that itself `LoadLibrary`s a second DLL, or a COM/ActiveX object made
  with `CreateObject` (CLSID → registry), is out of scope.
- **"No source edits" — one practical caveat.** Your `Declare`s are untouched,
  but to *see* output from a headless build you add a small `Sub Main` + a
  console-print helper (above). That's test scaffolding, not a fusion requirement.
- **`--fuse-runtime` relies on VBStatic.** Fusing `msvbvm60` is done by
  LinkAlchemy's VBStatic (bundled at `tools/VBStatic.exe`); its constraints apply —
  Standard-EXE `Sub Main` projects work; form/OCX-heavy projects are less tested.
- **Runtime-identity / loader-lock caveats carry into the VB exe.** The fused C
  DLL still must not `LoadLibrary`/COM-init/thread-join during its own init, and
  still can't read its own `.rsrc`. Loader-aware guest code can detect the fused
  case with `GetModuleHandle("msvbvm60.dll") = 0` — see `VB6_FUSION_NOTES.md` §8.

### Tools
`vbcapture.py` (debugger capture) · `vbobj_extern.py` (thunk→extern) ·
`tlsinit.py` (TLS CRT-init object) · `fzmeta.py` (build-info record) ·
`vbfuse.py` (the one command) · `trace_build.py` (original investigation probe)

The UCL sample itself (third-party GPL binaries) lives outside this repo under
`vbleg/`; these tools take paths as arguments.
