# exestuff — static DLL stuffing into a post-compiled VB6 exe

Take a **finished** VB6 `.exe` (native or p-code) that calls a C DLL via
`Declare Lib "foo.dll"`, and fuse the DLL straight into the exe by PE surgery —
**no VB6, no LINK.EXE, no OBJ capture, no build tools.** 32-bit (PE32/i386) only.

`exestuff app.exe foo.dll  ->  app_stuffed.exe` that runs with no `foo.dll`.

Standalone project with its **own forked copies** of the dll2lib pieces (so they
can be hacked on without touching the base app).

## Why it's cleaner than link-time fusion (vbfuse)

- Works on any shipped exe — no source, no `.vbp`, no toolchain.
- No LINK means none of the link-time headaches: no `/OPT:NOREF`, no
  `__ImageBase`, no export-pre-pass decoration gotchas, no `lib.exe`.
- `jmp rel32` thunk patches are self-relative → **no relocation needed**.

## Key findings (measured on a real VB6 exe)

- **VB6 strips relocations.** The test exe has `IMAGE_FILE_RELOCS_STRIPPED`, no
  `.reloc`, fixed base `0x400000`. So we **bake absolute addresses** into the
  stuffed DLL at `0x400000 + new_rva` and **skip the reloc-table merge entirely**.
  (If a future target *does* have relocs, we'd add the DLL's HIGHLOW entries to
  its `.reloc`; not needed for VB6.)
- The exe imports **only `msvbvm60.dll`**; the `Declare`d DLL is *not* in the
  import table (it's resolved at runtime by `DllFunctionCall`).
- The `Declare` thunks are present verbatim in `.text` (native, even in p-code):
  `A1 <cache> 0B C0 74 02 FF E0 68 <struct> B8 <DllFunctionCall> FF D0 FF E0`,
  where `<struct> = {&"lib", &"func", ...}` lets us recover the DLL/func names.

## Staged plan — ALL GREEN ✅ (end-to-end working)

- **S0** fork `pe32.py`; parse the target exe. ✅
- **S1** `pewrite.py`: append a section + fix headers; exe still runs. ✅
- **S2** find + decode the `Declare` thunks in `.text`. ✅
- **S3** flatten the DLL to one placeable blob; **bake every HIGHLOW reloc by a
  single constant `delta`** (= `exe_base - dll_base + shift`) since the target is
  fixed-base. Fix the ILT named-import RVAs by `shift`. ✅
- **S4** append the DLL blob as one RWX `.stuff` section. ✅
- **S5** merge the import table: new descriptor array (exe's copied + the DLL's,
  RVA fields `+= shift`) in a `.stimp` section, repoint the import data dir. ✅
- **S6** rewrite each target thunk to `E9 <rel32>` → stuffed export + `int3`
  (self-relative, no reloc, no decoration). ✅
- **S7** inject a `.sttls` section with a TLS directory + callback that runs the
  DLL's entry (CRT/DllMain) on `PROCESS_ATTACH`. ✅
- **Final** `tests/run.py`: stuff `ucl_dll.dll` into `stufftest.exe`, remove the
  DLL, run → **`OK in=2250 comp=64 dec=2250`**. ✅

The stuffed exe imports `kernel32 + msvbvm60 + msvcrt` (the DLL's deps merged in),
has a TLS dir, and runs with no `ucl_dll.dll`.

## Validated targets

- **UCL** (dynamic CRT, small, exe) — `tests/run.py` ✅
- **SQLite** (`sqlite3_vb6.dll`, 1 MB, **static CRT**, 45 exports, full sqlite4vb
  stack, exe) — `tests/run_sql.py` ✅ → `OK version=3.53.0 count=2 row2=fused`
  with the DLL deleted.
- **ActiveX DLL** (`sqlite4vb.dll`, Type=OleDll, **relocatable**, base 0x11000000)
  with `sqlite3_vb6.dll` stuffed in ✅ — registers (`regsvr32`, exit 0), and
  `CreateObject("SqlLite4VB.cSQLite")` runs the fused engine standalone
  (`version=3.53.0 / count=2 / row2=fused`), clean teardown. (Manual test; a
  32-bit COM host is required — `SysWOW64\cscript.exe` / `SysWOW64\regsvr32.exe`.)

### Relocatable targets (the "usurp + expand the reloc table" path)
A VB6 **exe** is reloc-stripped (fixed base) so we just bake. An **ActiveX DLL**
has a `.reloc` (ASLR), so `expand_relocs()` rebuilds the target's base-reloc table
= its existing blocks + HIGHLOW entries for **every stuffed absolute** (the DLL's
relocs at their new RVAs) **and the injected TLS directory's 5 VA fields**, into a
new `.streloc` section, repointing data dir 5. Verified it loads *and* relocates
to a non-preferred base.

### Two gotchas that each cost a crash
1. **TLS stub byte-math.** `call rel32` is relative to the address *after* the
   5-byte instruction (`entry - (call_rva + 5)`), and any `jXX` must land exactly
   on its target. An off-by-one jumps 1 byte into `DllMainCRTStartup` → CRT never
   inits → first `malloc` faults. (Dynamic-CRT DLLs hide it.)
2. **Forward ALL DllMain reasons, not just ATTACH.** The MSVC CRT registers an
   **FLS callback** in `DllMainCRTStartup(ATTACH)` and unregisters it with
   `FlsFree` on **DETACH**. If the TLS stub gates on ATTACH only, DETACH never
   runs, the FLS callback dangles, and at process teardown **ntdll's FLS cleanup
   calls the stale pointer into the (now-unmapped) stuffed region → AV**. Only
   bites DLL targets (unmapped mid-shutdown), not exes. The stub forwards every
   reason; `FlsFree` then runs and teardown is clean (`regsvr32` exits 0).

## Not yet / scope

- Delay/bound imports in the DLL: refused via pe32. Resources (`.rsrc`) skipped.
- ActiveX validated manually; not yet a committed automated test (needs COM
  register + a 32-bit host).

## Files

| File | Role |
|---|---|
| `pe32.py` | forked PE32 reader |
| `pewrite.py` | PE section-append / header patching (the writer) |
| `tests/corpus/` | `stufftest.*` (VB6 source + exe) + `ucl_dll.dll` |

## Test target

`tests/corpus/stufftest.exe` — a normal native VB6 exe: `Sub Main` compresses a
buffer via `CUclCompression` (5 `Declare`s to `ucl_dll.dll`), checks the
roundtrip, and writes `OK in=.. comp=.. dec=..` to `stufftest_result.txt`. Build
it with VB6 `/make` on `stufftest.vbp`; run it with `ucl_dll.dll` present.
