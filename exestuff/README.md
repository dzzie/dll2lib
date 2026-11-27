# exestuff

**Statically fuse a C DLL into a *finished* VB6 exe — by PE surgery alone.**

```
exestuff app.exe foo.dll [--out app_stuffed.exe] [--console] [--no-tls]
```

`--console` flips the stuffed exe to the CONSOLE subsystem, so a VB
`ConsolePrint`-style `Sub` (kernel32 `WriteFile` on `GetStdHandle`) reaches
stdout — the tests use this so their output is visible and rerunnable.

Takes an already-compiled VB6 `.exe` that calls `foo.dll` via
`Declare Lib "foo.dll"`, injects the DLL's code straight into the exe, rewrites
the `Declare` thunks to jump into it, and writes a standalone exe that runs with
**no `foo.dll`**. 32-bit (PE32/i386) only.

No VB6, no `LINK.EXE`, no OBJ capture, no build tools — pure Python on the
finished binary. (Contrast with the sibling `vbfuse`, which fuses at *link* time
and needs VB6 + the toolchain.)

## How it works

1. **Find the `Declare` thunks** in `.text` — the 25-byte native stub VB6/C2
   emits for each `Declare` (present even in a p-code build). Each points at a
   `{&"lib", &"func"}` struct, so we recover which DLL/function it is.
2. **Place the DLL.** Flatten its sections into one blob. Because a VB6 exe is
   **reloc-stripped / fixed-base** (`0x400000`), we just add a single constant
   `delta` to every HIGHLOW relocation slot — no symbol resolution, no reloc
   table to merge. Append it as one RWX `.stuff` section.
3. **Merge imports.** The DLL's own imports (e.g. `msvcrt`, `kernel32`) are added
   to the exe's import table (exe descriptors copied + the DLL's, RVA-shifted),
   in a `.stimp` section; the import directory is repointed. The loader resolves
   them normally.
4. **Rewrite the thunks** to `jmp rel32 → stuffed export` + `int3`. Self-relative,
   so no relocation and none of the link-time decoration gotchas.
5. **TLS init.** Inject a TLS directory + callback (`.sttls`) that runs the DLL's
   `DllMainCRTStartup` before the entry point, so a static-CRT DLL's heap / global
   ctors / `DllMain` are initialized. VB6 exes have no TLS dir, so it's a clean add.

## Status

End-to-end working on both CRT flavors — see `notes.md` for the staged breakdown.

- `tests/run.py` — **UCL** (dynamic CRT) stuffed into `stufftest.exe`, DLL removed,
  still `OK in=2250 comp=64 dec=2250`.
- `tests/run_sql.py` — **SQLite** (`sqlite3_vb6.dll`, 1 MB, **static CRT**, 45
  exports, full sqlite4vb OO stack) stuffed into `stufftest_sql.exe`, DLL removed,
  still `OK version=3.53.0 count=2 row2=fused` — the TLS-injected `DllMainCRTStartup`
  makes the static CRT heap work.
- `tests/run_activex.py` — **ActiveX DLL** (`sqlite4vb.dll`, relocatable) with
  SQLite stuffed in, registered and driven over COM with the C DLL removed:
  `version=3.53.0 / count=2 / row2=fused`, clean teardown. (Needs 32-bit Python;
  see `tests/corpus_activex/`.)

```
> python tests/run.py
[S2] thunks: SetLevel, LastError, Init, Compress, DeCompress
[S3] blob 24576 bytes @ rva 0x7000; baked 67 relocs
[S4] appended .stuff at 0x7000
[S5] merged imports: 1 exe + 2 dll -> .stimp @ 0xD000
[S6] rewrote 5 thunks -> jmp into .stuff
[S7] TLS callback -> DLL entry (CRT init)
STUFF TEST: PASS  ->  OK in=2250 comp=64 dec=2250
```

## Scope / limits

- Works on both **reloc-stripped** targets (a standard VB6 exe, fixed base — just
  bake) and **relocatable** ones (an **ActiveX DLL**, which has a `.reloc` for
  ASLR — the stuffed code's relocs + the TLS directory's VA fields are merged into
  the target's base-reloc table). Validated: `sqlite3_vb6.dll` fused into
  `sqlite4vb.dll` (ActiveX), usable via COM with the C DLL removed. (A 32-bit COM
  host — `SysWOW64\cscript.exe` / `regsvr32.exe` — is needed to register/run a
  32-bit in-proc DLL.)
- The fused DLL must be PE32/i386 with a `.reloc`, no delay/bound imports, no own
  TLS directory (refused via `pe32`). `.rsrc` is skipped.
- Same runtime-identity caveats as any static fusion (`GetModuleHandle(self)` = 0,
  no own resources).

## Files

| File | Role |
|---|---|
| `exestuff.py` | the tool (find thunks → place → merge imports → rewrite → TLS) |
| `pe32.py` | forked PE32 reader |
| `pewrite.py` | PE writer: append sections, patch headers / data directories |
| `tests/run.py` | regression test |
| `tests/corpus/` | `stufftest.*` (VB6 source + exe) + `ucl_dll.dll` |
| `tests/make_samples.py` | regenerates the committed stuffed sample binaries |

Each corpus also ships the **stuffed sample binaries** themselves, committed for
analysis tooling (e.g. vbdec) — both a native-compiled build (`*_stuffed`) and a
**P-code**-compiled build (`*_stuffed_p`) of every target, so no VB6 or stuffing
run is needed to inspect a finished fused binary. Regenerate with
`python tests/make_samples.py` (needs VB6 for the P-code compiles).

## Credit

Shares its DNA with **dll2lib / vbfuse** (same project) — the PE reader, the
reloc/import/export understanding, the Declare-thunk rewrite (ported from
VB6-LinkAlchemy's VBExtern by UltraAlex0), and the TLS-callback CRT-init trick.
