# Example 02 — fully standalone SQLite app (C DLL **and** VB runtime fused)

The showcase: a VB6 app built on the real **sqlite4vb** object‑oriented classes,
fused into a **single exe that depends on nothing but base Windows DLLs** — no
`sqlite3_vb6.dll`, no `msvbvm60.dll`.

### Files
- `SqlApp.vbp` / `modMain.bas` — the app. `Sub Main` opens a `:memory:` DB and
  **puts the engine through its paces**, printing each result to the console
  (built with `--console`): creates a `langs` table, bulk-inserts a dataset in
  one transaction, then runs an ordered table dump, aggregates
  (`COUNT/MIN/MAX/AVG`), a `GROUP BY`, a **parameterized** (`?`-bound) query, and
  a transaction **rollback** (ACID check).
- `modSQLite.bas`, `cSQLite.cls`, `cSQLiteAPI.cls`, `cSQLiteResults.cls`,
  `cSQLiteStatement.cls`, `cSQLiteColumn.cls`, `cSQLiteSchema.cls` — the real
  **sqlite4vb** OO class library (45 `Declare`s to `sqlite3_vb6.dll`),
  **unmodified**.
- `sqlite3_vb6.dll` — the SQLite engine (static‑CRT build) to fuse.
- `sqlapp_fused.exe` — the prebuilt fully‑standalone result (checked in).

  (The VB6‑runtime fuser, `VBStatic.exe`, lives at the repo's `tools/` and is
  located automatically — from VB6‑LinkAlchemy; MIT, see below.)

### Build
```
python build.py            (or:  build.cmd)    native-compiled -> sqlapp_fused.exe
python build.py --pcode    P-code-compiled   -> sqlapp_fused_p.exe
python build.py --run      build, then run (prints to the console)
```
`build.py` invokes
`vbfuse SqlApp.vbp --fuse sqlite3_vb6.dll --fuse-runtime …\msvbvm60.dll --console`
(`VBStatic.exe` is auto‑located in `tools/`). `dumpbin /exports sqlapp_fused.exe`
lists all 45 fused `vb6_sqlite3_*` functions at their RVAs — the fused SQLite
engine is labelled in the exe's own export table, even though the exe still
imports only base Windows DLLs. `--pcode` fuses a P-code build the same way
(runtime included).

### Expected output
```
Load state at process start (GetModuleHandle):
    msvbvm60.dll    : NOT loaded -> FUSED
    sqlite3_vb6.dll : NOT loaded -> FUSED
  -> neither is an import / load-time dependency.

SQLite engine version (from the fused code): 3.53.0
Opened an in-memory database (:memory:).

Inserted 8 rows in one transaction; last rowid = 8.

[1] SELECT * ORDER BY year
    name          year   paradigm
    ------------ -----   --------------
    C             1972   imperative
    Haskell       1990   functional
    Python        1991   multi-paradigm
    JavaScript    1995   multi-paradigm
    VB6           1998   event-driven
    SQLite        2000   embedded-db
    Go            2009   concurrent
    Rust          2010   systems

[2] aggregates (COUNT / MIN / MAX / AVG of year)
    count   = 8
    oldest  = 1972 (C)
    newest  = 2010 (Rust)
    avg year= 1995.6

[3] GROUP BY paradigm
    multi-paradigm   : 2
    concurrent       : 1
    ...

[4] parameterized: SELECT name,year WHERE year >= ?  (bind 2000)
    SQLite        2000
    Go            2009
    Rust          2010

[5] transaction rollback
    before          : 8 rows
    inside txn       : 0 rows (InTransaction=True, RowsAffected=8)
    after rollback   : 8 rows -> restored (ACID OK)

Load state after all that work:
    sqlite3_vb6.dll : NOT loaded -> FUSED
  -> still 0: every query above ran from the fused engine.

[SUCCESS] A full SQLite engine + the VB6 runtime put through its
          paces from one self-contained exe. Everything is awesome.
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
  into the exe. `VBStatic.exe` (in the repo's `tools/`) is built from that project (MIT).
  - https://github.com/ultraalex00/VB6-LinkAlchemy
  - https://www.vbforums.com/showthread.php?912383-VB6-LinkAlchemy-Embedding-MSVBVM60-DLL-into-EXE-DLL
- **sqlite4vb** VB6 classes © David Zimmer / sandsprite.com (MIT).
- **SQLite** is public domain (https://sqlite.org); `sqlite3_vb6.dll` is a VB6‑friendly build.
