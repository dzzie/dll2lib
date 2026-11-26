# Example 01 — fuse a C DLL (UCL compression)

A VB6 app that calls a C compression DLL (`ucl_dll.dll`) via `Declare`, fused
into a standalone exe that needs no `ucl_dll.dll` at runtime.

### Files
- `UclTest.vbp` / `modMain.bas` / `CUclCompression.cls` — the VB6 app.
  `Sub Main` compresses a buffer, decompresses it, checks the roundtrip, and
  prints a report to the console (built with `--console`). The
  `Declare ... Lib "ucl_dll.dll"` lines in `CUclCompression.cls` are left
  **exactly as written** — fusion needs no source edit.
- `ucl_dll.dll` — the C DLL to fuse.
- `ucltest_fused.exe` — the prebuilt fused result (checked in for analysis).

### Build
```
python build.py            (or:  build.cmd)
python build.py --run      build, then run (prints to the console)
```
`build.py` invokes `vbfuse UclTest.vbp --fuse ucl_dll.dll --console --export-fused`.
`--export-fused` means the fused functions show up in the exe's own export table,
so `dumpbin /exports ucltest_fused.exe` lists `Compress`, `DeCompress`, … at
their fused RVAs — handy for poking at the result.

### Expected output
```
  input        : 2250 bytes
  compressed   : 64 bytes  (35.2x smaller)
  decompressed : 2250 bytes
  roundtrip    : OK - matches the original
  ucl_dll.dll  : NOT loaded -> FUSED

  --- original  (first 48 of 2250 bytes) ---
    0000  54 68 65 20 71 75 69 63 6B 20 62 72 6F 77 6E 20  The quick brown
    0010  66 6F 78 20 6A 75 6D 70 73 20 6F 76 65 72 20 74  fox jumps over t
    0020  68 65 20 6C 61 7A 79 20 64 6F 67 2E 20 54 68 65  he lazy dog. The
    ...  (2202 more bytes)

  --- compressed  (all 64 bytes, produced by the fused C code) ---
    0000  FF 54 68 65 20 71 75 69 63 FF 6B 20 62 72 6F 77  .The quic.k brow
    0010  6E 20 FF 66 6F 78 20 6A 75 6D 70 FF 73 20 6F 76  n .fox jump.s ov
    0020  65 72 20 74 77 1E 6C 61 7A FE 79 20 64 6F 67 2E  er tw.laz.y dog.
    0030  20 CA 2C AA A3 20 51 20 00 00 00 00 00 90 FF 00   .,.. Q ........

  --- decompressed  (first 48 of 2250 bytes) ---
    0000  54 68 65 20 71 75 69 63 6B 20 62 72 6F 77 6E 20  The quick brown
    0010  66 6F 78 20 6A 75 6D 70 73 20 6F 76 65 72 20 74  fox jumps over t
    0020  68 65 20 6C 61 7A 79 20 64 6F 67 2E 20 54 68 65  he lazy dog. The
    ...  (2202 more bytes)

[SUCCESS] The dense 'compressed' block above round-trips byte-for-byte ...
```
The `compressed` dump is visibly packed binary (UCL's `FF` literal-run markers,
back-references, length codes); the `decompressed` dump matches the original
byte-for-byte — all produced by the C code **fused into the exe**. Delete
`ucl_dll.dll` first if you like; the fused exe doesn't need it.

### Credits
- UCL compression library © Markus F.X.J. Oberhumer — https://www.oberhumer.com/opensource/ucl/ (GPL).
- The VB6 UCL wrapper sample is a long-standing community sample; `ucl_dll.dll`
  here is that GPL wrapper. Fusion mechanics build on **VB6‑LinkAlchemy** by
  **UltraAlex0** (see the top-level README and `../../VB6_FUSION_NOTES.md`).
