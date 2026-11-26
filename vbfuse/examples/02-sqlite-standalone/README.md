# Example 02 — fully standalone SQLite app (C DLL **and** VB runtime fused)

The showcase: a VB6 app built on the real **sqlite4vb** object‑oriented classes,
fused into a **single exe that depends on nothing but base Windows DLLs** — no
`sqlite3_vb6.dll`, no `msvbvm60.dll`.

### Files
- `SqlApp.vbp` / `modMain.bas` — the app: `Sub Main` opens a `:memory:` DB,
  creates a table, inserts rows, queries them back, and **prints a report to the
  console** (built with `--console`).
- `modSQLite.bas`, `cSQLite.cls`, `cSQLiteAPI.cls`, `cSQLiteResults.cls`,
  `cSQLiteStatement.cls`, `cSQLiteColumn.cls`, `cSQLiteSchema.cls` — the real
  **sqlite4vb** OO class library (45 `Declare`s to `sqlite3_vb6.dll`),
  **unmodified**.
- `sqlite3_vb6.dll` — the SQLite engine (static‑CRT build) to fuse.
- `VBStatic.exe` — fuses the VB6 runtime (from VB6‑LinkAlchemy; MIT, see below).
- `sqlapp_fused.exe` — the prebuilt fully‑standalone result (checked in).

### Build
```
python build.py            (or:  build.cmd)
python build.py --run      build, then run (prints to the console)
```
`build.py` invokes
`vbfuse SqlApp.vbp --fuse sqlite3_vb6.dll --fuse-runtime …\msvbvm60.dll --vbstatic VBStatic.exe --console`.

### Expected output
```
====================================================
  SQLite + VB runtime  -  fully standalone (vbfuse)
====================================================
Fused in: sqlite3_vb6.dll (SQLite engine)
          msvbvm60.dll   (the VB6 runtime, via VBStatic)

Load state at process start (GetModuleHandle):
    msvbvm60.dll    : NOT loaded -> FUSED
    sqlite3_vb6.dll : NOT loaded -> FUSED
  -> neither is an import / load-time dependency.

  SQLite version         : 3.53.0
  opened                 : :memory:
  created + inserted     : table t, 2 rows
  SELECT COUNT(*)        : 2
  SELECT body WHERE id=2 : 'fused'

Load state after all queries ran:
    sqlite3_vb6.dll : NOT loaded -> FUSED
  -> still 0: the engine never touched the DLL on disk.

[SUCCESS] A full SQLite engine + the VB6 runtime, running
          from one self-contained exe. Everything is awesome.
```

`Sub Main` calls `GetModuleHandle` **before and after** running the engine — both
the VB runtime and the SQLite engine report `0` (not mapped) the whole time; a
normal VB6 exe has `msvbvm60` mapped before `Main` even runs. Three independent
confirmations it's truly standalone:

- `dumpbin /imports sqlapp_fused.exe` shows only `ADVAPI32 / GDI32 / KERNEL32 /
  OLE32 / OLEAUT32 / USER32` — **no `msvbvm60.dll`, no `sqlite3_vb6.dll`.**
- `sqlite3_vb6.dll` is still unloaded after every query runs.
- **Delete `sqlite3_vb6.dll` and the exe runs identically** (verified).

**Fusion-aware `EnsureDLL`.** sqlite4vb's `EnsureDLL` normally `LoadLibrary`s the
DLL from disk. We added a one-line guard (`modSQLite.bas`): if
`GetModuleHandle("msvbvm60.dll")` is `0`, the VB runtime is fused — so the engine
is too — and it returns success without touching disk. In a normal, non-fused
build `msvbvm60` *is* loaded, so the guard is skipped and `EnsureDLL` behaves
exactly as before.

### How two runtimes get initialized
- SQLite's **static CRT** is initialized by an injected **TLS callback** the
  loader runs before the VB entry (so `malloc` works).
- The **VB6 runtime** is initialized by VBStatic's `_VBStaticEntry`, which runs
  `msvbvm60`'s `DllMain` then jumps to the VB `Sub Main`.

### Credits
- **VB6‑LinkAlchemy** / **VBStatic** by **UltraAlex0** — fuses `MSVBVM60.DLL`
  into the exe. `VBStatic.exe` here is built from that project (MIT).
  - https://github.com/ultraalex00/VB6-LinkAlchemy
  - https://www.vbforums.com/showthread.php?912383-VB6-LinkAlchemy-Embedding-MSVBVM60-DLL-into-EXE-DLL
- **sqlite4vb** VB6 classes © David Zimmer / sandsprite.com (MIT).
- **SQLite** is public domain (https://sqlite.org); `sqlite3_vb6.dll` is a VB6‑friendly build.
