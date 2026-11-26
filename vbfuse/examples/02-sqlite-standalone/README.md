# Example 02 — fully standalone SQLite app (C DLL **and** VB runtime fused)

The showcase: a VB6 app built on the real **sqlite4vb** object‑oriented classes,
fused into a **single exe that depends on nothing but base Windows DLLs** — no
`sqlite3_vb6.dll`, no `msvbvm60.dll`.

### Files
- `SqlApp.vbp` / `modMain.bas` — the app: `Sub Main` opens a `:memory:` DB,
  creates a table, inserts rows, queries them back, writes the result.
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
python build.py --run      build, run, and write result.txt
```
`build.py` invokes
`vbfuse SqlApp.vbp --fuse sqlite3_vb6.dll --fuse-runtime …\msvbvm60.dll --vbstatic VBStatic.exe`.

### Expected
```
version=3.53.0
opened :memory:
count=2 row2=fused
OK cSQLite classes fused
```
`dumpbin /imports sqlapp_fused.exe` shows only `KERNEL32 / USER32 / GDI32 /
ADVAPI32 / OLE32 / OLEAUT32` — **no `msvbvm60.dll`, no `sqlite3_vb6.dll`.**

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
