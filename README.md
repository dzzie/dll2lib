# dll2lib + vbfuse

**Fuse DLLs into the program that uses them** — so it ships as one self‑contained
executable with no DLLs beside it at runtime.

Two tools, one idea:

- **`dll2lib`** turns a shipped **PE32 (i386) DLL into a full *static* COFF
  `.lib`**. The library's code and data *are* the DLL's implementation, so a
  consumer links it and runs with **no DLL present at runtime** (the way Binary
  Soft's old "DLL to Lib" worked). This is **not** an import/stub lib.
- **`vbfuse`** is a front end built on `dll2lib` for the VB6 world: take a
  normally‑compiled VB6 app that calls C DLLs via `Declare Lib "foo.dll"`, and
  fuse those DLLs — and optionally **the VB6 runtime `msvbvm60.dll` itself** —
  straight into the `.exe`. **No source edits, no linker swap, no add‑in.**

The payoff: a VB6 application + its C DLLs + the VB runtime collapse into **one
exe that imports nothing but base Windows DLLs**.

## See it work

Both demos in [`vbfuse/examples/`](vbfuse/examples/) are built with `--console`
and print a report when run — the prebuilt exes are checked in, so you can run
them without building anything.

**`01-ucl-compression`** — a C compression DLL fused in:

```
  input        : 2250 bytes
  compressed   : 64 bytes  (35.2x smaller)
  decompressed : 2250 bytes
  roundtrip    : OK - matches the original
  ucl_dll.dll  : NOT loaded -> FUSED        (GetModuleHandle = 0)
[SUCCESS] Real UCL compression ran entirely from fused code.
```

**`02-sqlite-standalone`** — the SQLite engine **and** the VB6 runtime fused into
one exe (`dumpbin /imports` shows only `ADVAPI32/GDI32/KERNEL32/OLE32/OLEAUT32/USER32`):

```
  msvbvm60.dll    : NOT loaded -> FUSED     (GetModuleHandle = 0)
  sqlite3_vb6.dll : NOT loaded -> FUSED     (still 0 after every query)
  SQLite engine version: 3.53.0   (in-memory DB, 8-row dataset)
  ordered dump / aggregates / GROUP BY / parameterized query / txn rollback: all OK
[SUCCESS] A full SQLite engine + the VB6 runtime put through its paces from one exe.
```

---

## dll2lib — the engine

### How it works

A DLL with an intact `.reloc` table is nearly a relocatable object already.
dll2lib:

1. parses the PE (headers, sections, exports, imports, base relocations);
2. emits the sections as COFF sections (hand-written COFF — that's the product);
3. converts each HIGHLOW base relocation into a COFF `DIR32` relocation (the
   stored absolute value becomes an offset within the target section);
4. rebuilds the DLL's own imports as `.idata$2/$3/$4/$5/$6` so `link.exe`
   produces the final import table (the DLL's deps become the host's deps);
5. emits `_Name` + `__imp__Name` for every export (plus decorated `_Name@n`
   for stdcall), so both direct calls and `__declspec(dllimport)` resolve;
6. emits a `_<dll>_StaticInit` bootstrap that runs the DLL's `DllMain`/CRT
   init (`DLL_PROCESS_ATTACH`) — **the consumer must call it once** before
   using any export;
7. invokes MS `lib.exe` to wrap the object into a `.lib`.

### Usage

```
dll2lib foo.dll [/OUT:foo.lib] [/DEF:foo.def] [/DUMP]
```

- `/DUMP` — parse and print headers/sections/exports/imports/relocs + verdict.
- `/DEF:foo.def` — supply stdcall decoration via alias lines (`_Func@8=_Func`).
- Default: convert → write `foo.obj` → `lib.exe` → `foo.lib`.

Then in your program, call `foo_StaticInit()` once, then use the exports; link
against `foo.lib` with no reference to `foo.dll`. See [`examples/`](examples/)
for three runnable walkthroughs (a basic export, a DLL that calls `kernel32`,
and a real `/MT` C++ DLL with a `DllMain`).

### Scope & compatibility (v1)

dll2lib does **partial binary delinking**: it recovers enough object/linker
semantics to relink, without reconstructing the original compilation units.

| PE feature | Status |
|---|---|
| PE32 / i386 code, data, bss | **supported** |
| HIGHLOW base relocations | **supported** (→ COFF `DIR32`) |
| the DLL's own imports | **supported** (rebuilt as `.idata$*`) |
| exports (cdecl + stdcall `@n`) | **supported** (`_Name` + `__imp__Name`) |
| `DllMain` / static-CRT init | **supported** — one-shot, via `_StaticInit` (dll2lib) or a TLS callback (vbfuse) |
| multiple code sections | **supported** — merged into one `.text` (whole DLL carried; no dead-code elimination) |
| 16-byte-aligned data (SSE) | **supported** — data sections are 16-aligned |
| x64 / PE32+ | **refused** |
| reloc-stripped DLL | **refused** (rebuild `/FIXED:NO`) |
| bound imports | **refused** |
| delay-load imports | **refused** (parsed, not yet reconstructed) |
| own TLS directory (`__declspec(thread)`) | **refused** (can't merge two TLS dirs) |
| resources (`.rsrc`) | **skipped** — code runs; `LoadString`/icon/own-`HINSTANCE` lookups won't |
| 32/64-byte-aligned data (AVX/AVX-512) | **untested** |

Beyond what's refused above, static fusion has inherent limits (module identity,
resources, loader-lock, COM, mitigations). They're collected in
**[Limitations](#limitations)** below — worth a read before pointing it at
something new.

### Status

Staged, each gated by a link-and-run test (`tests/run_s0.py` … `run_s7_rsrc.py`):

- **S0** PE reader — validated against `dumpbin` on 8 system DLLs
- **S1** COFF writer — hand-built obj links + runs
- **S2** spine — real stdcall DLL → lib → runs with the DLL deleted
- **S3** exports — `__imp__` slots + cdecl/stdcall decoration
- **S4** imports — `.idata$*` rebuild (fused exe pulls `kernel32!lstrlenA`)
- **S5** relocs — data→code / data→data / code→data all converted
- **S6** bootstrap — `DllMain`/CRT init runs via `_<dll>_StaticInit`
- **S7** real-world hardening: a `/MT /GS` C++ DLL (CRT + global ctor +
  `DllMain`, ~1800 relocs) fuses and runs; multi-code-section **merge** (with an
  interleaved data section resolved to its own section, not the merged span);
  **TLS**, **bound** and **delay-load** imports cleanly refused; **resources**
  skipped.

All 11 stage tests green (`tests/run_s0.py` … `run_s7_rsrc.py`).

---

## vbfuse — standalone VB6 executables

[`vbfuse/`](vbfuse/) makes a VB6 project self-contained. A VB6
`Declare Lib "foo.dll"` is **not** an import — `msvbvm60`'s `DllFunctionCall`
does `LoadLibrary`/`GetProcAddress` at runtime, and VB6/C2 compiles each
`Declare` into a 25-byte thunk in the project `.OBJ`. So vbfuse can't just link
a `.lib`; it:

1. runs `VB6.EXE /make` **under a debugger** and captures the OBJs + the link
   command at the `LINK.EXE` spawn (VB6 deletes the OBJs afterward);
2. rewrites the project OBJ's `Declare` thunks into **linker externs**, using the
   DLL's own name as the marker — **no VB source edit**;
3. converts each DLL to a static `.lib` with dll2lib, and injects a **TLS
   callback** that runs each DLL's CRT/`DllMain` init at load (before the VB
   entry, so a static-CRT DLL's heap is ready);
4. relinks with VB6's own `LINK.EXE` (forcing `/OPT:NOREF`, since VB6's
   `/OPT:REF` would dead-strip the fused code).

With `--fuse-runtime`, it also fuses `msvbvm60.dll` via **VBStatic** (see
Credits) for a fully standalone exe.

```
vbfuse app.vbp --fuse foo.dll [--fuse bar.dll ...]
       [--fuse-runtime C:\Windows\SysWOW64\msvbvm60.dll [--vbstatic VBStatic.exe]]
       [--console] [--out fused.exe] [--run [-- args]]
```

- `--console` builds the exe with the CONSOLE subsystem, so a VB
  `ConsolePrint`-style `Sub` can write to stdout — handy for testing.
- The fused DLL's exports are re-emitted in the exe's own export table
  (name → fused RVA). No runtime effect; it's an analysis aid so
  `dumpbin /exports` / IDA can name the fused functions.

See [`vbfuse/README.md`](vbfuse/README.md), the full knowledge dump in
[`vbfuse/VB6_FUSION_NOTES.md`](vbfuse/VB6_FUSION_NOTES.md), and the runnable
demos in [`vbfuse/examples/`](vbfuse/examples/).

---

## Limitations

Read this before pointing it at something new — none of these are bugs, they're
the shape of what static fusion can and can't do.

**Refused outright** — dll2lib stops with a reason rather than emit a broken lib.
x64 / PE32+ images; reloc-stripped DLLs (rebuild `/FIXED:NO`); DLLs with **bound**
imports; DLLs with **delay-load** imports (parsed, not yet reconstructed); and
DLLs with their own **TLS directory** (`__declspec(thread)` or TLS callbacks —
two TLS dirs can't be merged). Check any DLL first with `dll2lib foo.dll /DUMP`.

**Lost runtime identity.** Fused code has no module of its own, so:
- `GetModuleHandle("foo.dll")` returns `0`, and there is no own `HINSTANCE`;
- `.rsrc` is dropped — `LoadString`, icons, message tables, version info, and any
  "load my own resource" call find nothing;
- a DLL that locates its own path/handle to open sidecar files will misbehave.

  (VBStatic special-cases this for `msvbvm60`; the generic engine does not.)

**`DllMain` lifecycle is partial.** `DLL_PROCESS_ATTACH` is driven once (CRT +
global ctors run); **thread-attach, thread-detach and process-detach are not
forwarded**, and a `FALSE` return from init is **not** propagated as a load
failure. Fine for compute libraries; a library with real per-thread setup or
shutdown work needs care.

**Init runs under loader lock.** The CRT-init TLS callback (and `DllMain`) run
while the loader lock is held, so a DLL whose init calls `LoadLibrary`, does COM
init, or joins a thread can **deadlock**. SQLite and UCL don't — it's the ceiling
of what's safely fuseable.

**Name-reached dependencies only.** Fusion covers code reached through the PE
import table or a VB6 `Declare "foo.dll"`. A **COM / ActiveX** dependency reached
via `CreateObject` → CLSID → registry is a different problem, out of scope.

**No dead-code elimination.** Multi-code-section DLLs are merged whole — the
entire DLL is carried, unused functions included. Trimming them is a separate
delinking problem.

**Image mitigations not reconstructed.** SEH/SafeSEH, CFG and load-config
metadata don't survive fusion — treat a fused build as losing them.

**Data alignment.** Data sections are 16-byte aligned (covers SSE); 32/64-byte
(AVX / AVX-512) aligned data is **untested**.

**vbfuse specifics.** x86 (32-bit) only; needs **VB6 (VB98)** and the **x86 MS
Build Tools** installed — it drives the real `VB6.EXE` and `LINK.EXE`. It works
from a *normally compiled* project with **no source edits**, but each fused DLL
must be dll2lib-convertible (see "Refused outright"). `--fuse-runtime` embeds
`msvbvm60` via VBStatic.

---

## Toolchain

Python 3 + MS Build Tools (x86: `cl` / `link` / `lib` / `dumpbin`, via
`vcvars32`); vbfuse additionally needs **VB6 (VB98)** installed. No third-party
Python dependencies — the PE reader and COFF writer are hand-rolled.

## Layout

| Path | Purpose |
|---|---|
| `pe32.py` | dependency-free PE32 reader |
| `coff.py` | hand-rolled i386 COFF object writer |
| `convert.py` | the converter (sections, relocs, exports, imports, bootstrap) |
| `msvc.py` | locate/run the x86 MS tools |
| `dll2lib.py` | the dll2lib CLI |
| `tests/run_s*.py` | staged build-and-run tests (S0–S7), each self-checking |
| `vbfuse/` | the VB6 fusion front end (`vbfuse.py`, `vbcapture.py`, `vbobj_extern.py`, `tlsinit.py`) |
| `vbfuse/examples/` | two runnable demos + their prebuilt fused exes |

## Credits & acknowledgements

The whole VB6 side of this project stands on **VB6‑LinkAlchemy** by
**UltraAlex0** — the project that pioneered embedding `MSVBVM60.DLL` into a VB6
EXE/DLL. Its **VBStatic** tool is what `vbfuse --fuse-runtime` uses to fuse the
VB6 runtime, and `vbfuse/vbobj_extern.py` is a direct Python port of its
**VBExtern** (the `Declare`‑thunk → linker‑extern rewrite). dll2lib itself takes
its COFF-object approach from LinkAlchemy's **VBStatic.bas**. Enormous thanks —
this would not exist without that work.

- VB6‑LinkAlchemy: https://github.com/ultraalex00/VB6-LinkAlchemy
- Write‑up: https://www.vbforums.com/showthread.php?912383-VB6-LinkAlchemy-Embedding-MSVBVM60-DLL-into-EXE-DLL

Other third‑party components used in the demos are credited in their example
folders: **sqlite4vb** (VB6 SQLite classes, © David Zimmer / sandsprite.com),
**SQLite** (public domain), **UCL** (© Markus F.X.J. Oberhumer), and the VB6
console helpers (wqweto; Karl E. Peterson's classic `MConsole.bas`).

## License

This project's own code (dll2lib + vbfuse) is **MIT** — see [`LICENSE`](LICENSE).
Bundled third‑party components keep their own licenses (VB6‑LinkAlchemy/VBStatic
MIT, sqlite4vb MIT, SQLite public‑domain, UCL GPL — so the example `ucl_dll.dll`
is GPL); the `LICENSE` file and example READMEs spell this out.

## Related work & prior art

dll2lib + vbfuse build on two well‑trodden ideas — turning a linked binary back
into relinkable objects, and rewriting an object file's symbols — specialized to
DLLs and wired into VB6.

**DLL → static library without source** (direct ancestors — a full
implementation, *not* an import stub):

- Binary Soft, *DLL to Lib* — the commercial tool this emulates:
  [softpedia](https://www.softpedia.com/get/Programming/Other-Programming-Files/DLL-to-Lib.shtml)
- CoderUpgrade, *Dll to Static Lib* — a later equivalent:
  [listing](https://dll-to-static-lib.software.informer.com/)
- (For contrast, the *common* `lib.exe /DEF` / MinGW `dlltool` route only makes an
  **import stub** that still needs the DLL at runtime — not this.)

**Delinking** — recovering relocatable objects from a linked binary. This is the
harder, general case: those binaries have no `.reloc`, so relocations must be
recovered by analysis. dll2lib sidesteps it entirely by reusing the DLL's own
relocation table (no disassembly):

- [jnider/delinker](https://github.com/jnider/delinker) — unlink an exe into `.o` files
- [vostok-delinker](https://github.com/srp-survarium/vostok-delinker) — old‑MSVC PE + PDB → per‑TU COFF
- [boricj's Ghidra delinker](https://news.ycombinator.com/item?id=35738758) — exports relocatable ELF; delinked a 7 MiB game
- [binja_delink](https://github.com/alecnunn/binja_delink) — Binary Ninja plugin
- LLVM **BOLT** keeps relocations via `--emit-relocs` (the "don't recover them later" approach)

**Object‑file / symbol rewriting** — the generic form of vbfuse's `Declare`→extern move:

- Agner Fog, [*objconv*](https://www.agner.org/optimize/#objconv) — convert COFF/OMF/ELF/Mach‑O, rename/modify symbols

**VB6 build interception** — prior approaches to the hook vbfuse does with a debugger:

- [VB6‑LinkAlchemy / VBStatic](https://github.com/ultraalex00/VB6-LinkAlchemy) by UltraAlex0 — embed `msvbvm60`; the inspiration ([write‑up](https://www.vbforums.com/showthread.php?912383-VB6-LinkAlchemy-Embedding-MSVBVM60-DLL-into-EXE-DLL))
- [Jim White's LinkTool](https://github.com/dzzie/addins/tree/master/LinkTool) — replaces `LINK.EXE`
- [John Chamberlain's Compiler Control](https://github.com/dzzie/addins/tree/master/CompilerControl99) — add‑in + `CreateProcess` API hook

dll2lib's own contribution is the **combination**: `.reloc`‑based DLL→lib
conversion (no disassembly) driven into a VB6 build via debugger‑intercepted
capture + on‑the‑fly `Declare`‑thunk rewriting — with no source edits, no
`LINK.EXE` swap, and no add‑in.
