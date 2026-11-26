# dll2lib

Convert a shipped **PE32 (i386) DLL into a full *static* COFF `.lib`** — the
library's code and data *are* the DLL's implementation, so a consumer can link
it and run with **no DLL present at runtime** (the way Binary Soft's old
"DLL to Lib" worked). This is **not** an import/stub lib.

## How it works

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

Inspired by / lifted from **VBStatic** (VB6-LinkAlchemy), which does exactly
this but hardwired for `msvbvm60.dll`.

## Usage

```
dll2lib foo.dll [/OUT:foo.lib] [/DEF:foo.def] [/DUMP]
```

- `/DUMP` — parse and print headers/sections/exports/imports/relocs + verdict.
- `/DEF:foo.def` — supply stdcall decoration via alias lines (`_Func@8=_Func`).
- Default: convert → write `foo.obj` → `lib.exe` → `foo.lib`.

Then in your program, call `foo_StaticInit()` once, then use the exports;
link against `foo.lib` with no reference to `foo.dll`.

See [`examples/`](examples/) for three runnable walkthroughs (a basic export,
a DLL that calls `kernel32`, and a real `/MT` C++ DLL with a `DllMain`).

## Scope (v1)

- **In:** PE32 / i386, HIGHLOW relocations, DLL has `.reloc`.
- **Out / refused:** x64/PE32+, reloc-stripped DLLs (rebuild `/FIXED:NO`),
  bound imports, TLS directory. Resources (`.rsrc`) are skipped in v1.
- Merging code sections into one section means the **whole** DLL is carried
  (no dead-code elimination — that's a separate delinking problem).

## Toolchain

Python 3 + MS Build Tools (x86: `cl` / `link` / `lib` / `dumpbin`, via
`vcvars32`). No third-party Python dependencies — the PE reader and COFF
writer are hand-rolled.

## Layout

| File | Purpose |
|---|---|
| `pe32.py` | dependency-free PE32 reader |
| `coff.py` | hand-rolled i386 COFF object writer |
| `convert.py` | the converter (sections, relocs, exports, imports, bootstrap) |
| `msvc.py` | locate/run the x86 MS tools |
| `dll2lib.py` | CLI |
| `tests/run_s*.py` | staged build-and-run tests (S0–S6), each self-checking |

## Status

Staged, each gated by a link-and-run test (`tests/run_s0.py` … `run_s6.py`):

- **S0** PE reader — validated against `dumpbin` on 8 system DLLs
- **S1** COFF writer — hand-built obj links + runs
- **S2** spine — real stdcall DLL → lib → runs with the DLL deleted
- **S3** exports — `__imp__` slots + cdecl/stdcall decoration
- **S4** imports — `.idata$*` rebuild (fused exe pulls `kernel32!lstrlenA`)
- **S5** relocs — data→code / data→data / code→data all converted
- **S6** bootstrap — `DllMain`/CRT init runs via `_<dll>_StaticInit`
- **S7** real-world hardening:
  - a real `/MT /GS` C++ DLL (CRT + global ctor + `DllMain`, ~1800 relocs) fuses and runs
  - **section-merge** — multiple code sections joined by reloc-less `rel32` merged into one `.text`
  - **TLS** — a DLL with a TLS directory is cleanly refused
  - **resources** — `.rsrc` is skipped (code still works; resource lookups are a v2 item)

All 11 stage tests green (`tests/run_s0.py` … `run_s7_rsrc.py`).
