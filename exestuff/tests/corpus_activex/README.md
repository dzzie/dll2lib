# corpus_activex — stuffing an ActiveX DLL (relocatable target)

The real-world case: a VB6 **ActiveX DLL** (`Type=OleDll`) that wraps a C DLL via
`Declare`, fused into a self-contained component — no external C DLL at runtime.
Unlike a standard VB6 exe, an ActiveX DLL ships with a `.reloc` (ASLR), so this
exercises exestuff's reloc-table merge.

### Files
- **Source** of the ActiveX DLL (`sqlite4vb`, © David Zimmer / sandsprite.com, MIT):
  `sqlite4vb.vbp` (OleDll) + `modSQLite.bas` + `cSQLite*.cls` — the sqlite4vb OO
  class library (45 `Declare`s to `sqlite3_vb6.dll`). `_sqlite4vb.dll` is the
  binary-compatibility baseline the `.vbp` builds against (keeps COM GUIDs stable).
- `sqlite4vb.dll` — the prebuilt ActiveX DLL (the stuffing **target**).
- `sqlite3_vb6.dll` — the C SQLite engine (static CRT) to stuff in.
- `sqlite4vb_stuffed.dll` — the **prebuilt stuffed result** (checked in): a
  self-contained ActiveX DLL that needs no `sqlite3_vb6.dll`.
- `sqlite4vb_stuffed_p.dll` — the same, but built from a **P-code** compile of the
  ActiveX DLL (`_p`), for analysis tooling (e.g. vbdec) that wants both flavors.
  See `tests/make_samples.py`; both verified working over COM with the C DLL gone.

### What exestuff does here
`exestuff sqlite4vb.dll sqlite3_vb6.dll -> sqlite4vb_stuffed.dll`:
rewrites the 45 `Declare` thunks, appends the SQLite engine, merges imports, and —
because the target is relocatable — **expands the DLL's `.reloc`** with the stuffed
code's relocations and the injected TLS directory's VA fields (so it still
relocates under ASLR). A TLS callback runs `DllMainCRTStartup` (static-CRT init),
forwarding *all* DllMain reasons so `FlsFree` runs on DETACH and teardown is clean.

### Test it (`tests/run_activex.py`, needs 32-bit Python)
Stuffs, registers (per-user), removes `sqlite3_vb6.dll`, then drives it over COM
with a **32-bit** host and checks the output + clean exit:

```
> python tests/run_activex.py
version=3.53.0
count=2
row2=fused
--- ACTIVEX STUFF TEST: PASS  (cscript exit 0x0) ---
```

### Manual COM test
A 32-bit in-proc DLL needs a **32-bit** COM host (the 64-bit `cscript`/`regsvr32`
give error 429):

```
C:\Windows\SysWOW64\regsvr32.exe /s sqlite4vb_stuffed.dll
del sqlite3_vb6.dll
C:\Windows\SysWOW64\cscript.exe //nologo test.vbs    ' CreateObject("SqlLite4VB.cSQLite")
```
