# vbfuse examples

Each folder is a complete, buildable demo: the VB6 app sources, the C DLL to
fuse, a `build.py` / `build.cmd`, and the **prebuilt fused exe** (checked in so
you can inspect/run the result without building). Both are built with
`--console` and **print a report to the console when run**, so you can see the
fused code actually working.

| Folder | Fuses | Result |
|---|---|---|
| [`01-ucl-compression`](01-ucl-compression/) | a C compression DLL (`ucl_dll.dll`) | standalone compressor, no `ucl_dll.dll` |
| [`02-sqlite-standalone`](02-sqlite-standalone/) | SQLite (`sqlite3_vb6.dll`) **+** the VB6 runtime (`msvbvm60.dll`) | a VB6 SQLite app that imports **only base Windows DLLs** |

## Building

Needs **VB6 (VB98)** installed and the **x86 MS Build Tools** on PATH (open an
"x86 Native Tools Command Prompt for VS"). Then, in a demo folder:

```
python build.py            # or  build.cmd
python build.py --run      # build, then run (prints its report to the console)
```

The prebuilt `*_fused.exe` is already in each folder if you just want to analyze
or run it.

## Credits

The VB6‑runtime fusion (example 02's `--fuse-runtime`) is done by **VBStatic**,
part of **VB6‑LinkAlchemy** by **UltraAlex0** — the project that pioneered
embedding `MSVBVM60.DLL` into a VB6 EXE/DLL, and the direct inspiration for this
whole VB leg. `vbobj_extern.py` here is a Python port of its `VBExtern`.

- https://github.com/ultraalex00/VB6-LinkAlchemy
- https://www.vbforums.com/showthread.php?912383-VB6-LinkAlchemy-Embedding-MSVBVM60-DLL-into-EXE-DLL

Per-example third-party credits (UCL, sqlite4vb, SQLite) are in each folder's README.
