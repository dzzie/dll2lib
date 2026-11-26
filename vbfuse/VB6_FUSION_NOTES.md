# VB6 fusion — notes & hard-won knowledge

Everything learned wiring `vbfuse` (fuse a C DLL into a compiled VB6 exe with
no source edits, no `LINK.EXE` swap, no add-in). Companion to `README.md`.

---

## 1. How VB6 `/make` actually builds

Compiler: `C:\Program Files (x86)\Microsoft Visual Studio\VB98\VB6.EXE`
(1998 build, 32-bit). Headless compile:

```
VB6.EXE /make "proj.vbp" /out "err.log" /outdir "<dir>"
```

- `/out err.log` — build result. **Empty or `...succeeded` = OK**; anything else
  is a failure. Always use `/out`, or errors pop a **modal dialog** and hang.
- `/outdir <dir>` — where the EXE **and the intermediate `.OBJ`s** are written.

Under the hood VB6 spawns two tools from the VB98 dir (confirmed by debugging):

1. **`C2.EXE`** — VB6's code generator, once per module:
   ```
   C2 -il <temp> -f Form1.frm -W 3 -Gy -G5 -Gs4096 -dos -Zl -Fo"Form1.OBJ" -QIfdiv -ML -basic
   ```
   Produces one `<name>.OBJ` per `.frm`/`.cls`/`.bas`, **plus the project's main
   `<exename>.OBJ`**.
2. **`LINK.EXE`** (MS linker 6.00.8168) — links them:
   ```
   LINK <objs...> "VB98\VBAEXE6.LIB" /ENTRY:__vbaS /OUT:"app.exe"
        /BASE:0x400000 /SUBSYSTEM:WINDOWS,4.0 /VERSION:1.0
        /INCREMENTAL:NO /OPT:REF /MERGE:.rdata=.text /IGNORE:4078
   ```

**VB6 deletes the `.OBJ`s immediately after linking.** So any OBJ-level work must
grab them *during* the build — we do it with a debugger (see §4).

### Source encoding (the #1 time-sink)
Every `.vbp/.bas/.cls/.frm` **must be CRLF + ANSI (Windows-1252), no BOM.** LF
line endings → VB6 rejects the file with the useless `'X' could not be loaded`.
When generating sources programmatically: `open(path, "w", newline="",
encoding="latin-1")` and write `\r\n`.

### Headless testing
A compiled VB6 EXE has **no console** (`Debug.Print` goes nowhere). Make a
`Startup = "Sub Main"` project (no form), do the work in `Sub Main`, take
parameters from `Command$`, **write the result to a file**, then end. Read the
file back. (OCX/ActiveX projects additionally need an **elevated** shell; pure
code referencing only `stdole2.tlb` compiles non-elevated.)

---

## 2. Why fusion isn't just "link a .lib"

A VB6 `Declare Function Foo Lib "foo.dll" Alias "Bar" (...)` does **not** create
an import-table entry. `msvbvm60`'s `DllFunctionCall` does
`LoadLibrary("foo.dll")` + `GetProcAddress("Bar")` **at runtime** (lazily, cached
after first call). So a compiled VB6 exe references the DLL **by name as a
string**, not through the PE import table — and relinking alone can't satisfy it.

VB6/C2 compiles each `Declare` into a **25-byte thunk in the project `.OBJ`**
(not the OBJ of the module where the `Declare` is written — in a class module
the `Declare`s still end up in the *main* project OBJ):

```
A1 <cache:4>           mov eax,[cache]        ; cached resolved address
0B C0                  or  eax,eax
74 02                  je  +2
FF E0                  jmp eax                ; fast path once resolved
68 <declare_struct:4>  push offset struct     ; struct = { &"lib", &"func", ... }
B8 <DllFunctionCall:4> mov eax, offset DllFunctionCall
FF D0                  call eax
FF E0                  jmp eax
```

with DIR32 relocations at **+1** (cache), **+12** (struct), **+17** (callee).
The `struct` (in a data section) holds DIR32 pointers to the lib-name and
func-name strings — that's how we recover which DLL/function each thunk is for.

---

## 3. The fusion technique (what `vbobj_extern` does)

Port of VB6-LinkAlchemy's `VBExtern.bas`. For each thunk whose **Lib name
matches** the target DLL, rewrite the 25 bytes to:

```
E9 <rel32>   jmp _<Func>       ; REL32 reloc to a NEW undefined external
CC CC ...    int3 padding
```

Tricks that make it cheap and safe:
- **Reuse the thunk's own `+1` relocation** as the new `REL32` (just change its
  symbol index → the new extern and type → `IMAGE_REL_I386_REL32`). No
  relocation table grows — only an undefined external symbol is appended.
- The old `+12`/`+17` relocations are left pointing into the dead `int3`
  padding; harmless (never executed), and their symbols still exist.
- **Marker = the DLL's real name.** VBExtern defaults to `Lib "<extern>"`, but
  `--placeholder:foo.dll` uses the real name as the marker → **no VB source
  edit**. The emitted extern is `_<Func>` (undecorated), which matches exactly
  the symbol `dll2lib` emits — so **no stdcall `@n` decoration is needed**.

---

## 4. Capturing the OBJs (what `vbcapture` does)

Run `VB6.EXE /make` as a **debugged process** (`CreateProcess` with
`DEBUG_PROCESS`, which also debugs children). On the `CREATE_PROCESS_DEBUG_EVENT`
for `LINK.EXE`:
- read the linker's command line (the OBJ paths + all flags), and
- copy the OBJs it names into a preserve dir **before VB6 deletes them**.

ctypes gotchas (64-bit Python debugging the 32-bit toolchain):
- **Set `argtypes`** on every API or 64-bit `HANDLE`s get truncated to int.
- Model `DEBUG_EVENT`'s union with real ctypes `Structure`/`Union` — do **not**
  hand-parse by byte offset (`0x400000` showing where `hProcess` should be was
  the giveaway that the offsets were wrong).
- Read a 32-bit child's command line via `NtQueryInformationProcess(
  ProcessWow64Information=26)` → 32-bit PEB `+0x10` (`ProcessParameters`) →
  `+0x40` (`CommandLine` `UNICODE_STRING`), all via `ReadProcessMemory`.
- Continue breakpoints with `DBG_CONTINUE`; pass other exceptions through with
  `DBG_EXCEPTION_NOT_HANDLED` so VB6's own handlers run.

VB6 writes the OBJs to `/outdir`; `vbcapture` preserves the exact paths named on
the link line into `<work>\obj\` and records the link command verbatim.

---

## 5. Relinking — two non-obvious rules

Replay the captured link line with VB6's own `LINK.EXE`, swapping the patched
OBJ in and adding the `dll2lib` `.lib`, **but**:

- **Use `/OPT:NOREF` (not VB6's default `/OPT:REF`).** `/OPT:REF` dead-strips
  the fused object (`LNK4089: all references ... discarded by /OPT:REF`) — a
  reference-tracking quirk with the rewritten thunks. With `/OPT:REF` the fused
  code is silently dropped and the `jmp _Func` lands on nothing → crash. Forcing
  `/OPT:NOREF` retains it.
- **Omit the dll2lib bootstrap (`_<dll>_StaticInit`) for DLLs that don't need
  CRT init.** The bootstrap references `___ImageBase`, which the VC6-era
  `LINK.EXE` does **not** provide → unresolved external. For a DLL with no C++
  global constructors (e.g. UCL — `level`/`ErrorString` are statically
  initialized, `strcpy`/`sprintf` come from the external `MSVCRT.dll`), skip it:
  call `convert(pe)` with `init_symbol=None`.

> **Open problem:** a C DLL that genuinely needs CRT init (C++ global ctors, a
> `/GS` cookie, etc.) *does* need its `DllMainCRTStartup` run once. There's no C
> entry point in a VB6 exe to call `StaticInit`, and VC6's linker lacks
> `__ImageBase`. Options to explore: emit an auto-initializer the VB runtime
> triggers, inject a synthetic `Declare`-style call, or define `___ImageBase`
> ourselves. Not needed for UCL; revisit for heavier DLLs (e.g. sqlite3).

---

## 6. The end-to-end pipeline (`vbfuse`)

```
vbfuse app.vbp --fuse foo.dll [--fuse bar.dll ...] [--out fused.exe] [--run -- args]
  1. vbcapture : VB6 /make under debugger -> OBJs + link line
  2. vbobj_extern: rewrite the project OBJ's `foo.dll` Declare thunks -> externs
  3. dll2lib   : foo.dll -> foo.lib  (no bootstrap)
  4. LINK.EXE  : captured args + patched OBJ + foo.lib, /OPT:NOREF -> fused exe
```

Proven on the UCL sample: a VB6 app that `Declare`s `ucl_dll.dll` fuses into a
standalone exe that compresses/decompresses correctly with the DLL deleted.
