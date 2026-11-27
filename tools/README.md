# tools/

Third‑party build tools bundled with the project so the demos build without fuss.

## `VBStatic.exe`

From **VB6‑LinkAlchemy** by **UltraAlex0** (MIT). `vbfuse --fuse-runtime` runs it
as a subprocess to embed the VB6 runtime (`msvbvm60.dll`) into the fused exe —
`VBStatic.exe msvbvm60.dll <main>.OBJ` merges the runtime into the captured main
project object and defines `_VBStaticEntry`, then vbfuse relinks.

`vbfuse` locates it here automatically (`find_vbstatic()`); override with
`--vbstatic <path>`. Only `--fuse-runtime` needs it — plain C‑DLL fusion doesn't.

- https://github.com/ultraalex00/VB6-LinkAlchemy
- https://www.vbforums.com/showthread.php?912383-VB6-LinkAlchemy-Embedding-MSVBVM60-DLL-into-EXE-DLL

See the top‑level `README.md` for full credits.
