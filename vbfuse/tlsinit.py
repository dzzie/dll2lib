#!/usr/bin/env python3
r"""
tlsinit.py  -  emit a COFF object that registers a TLS callback which the
Windows loader runs at process-attach (before the exe's entry point). The
callback forwards the loader-supplied (hInstance, reason, reserved) to each
fused DLL's original entry (DllMainCRTStartup), so the static CRT / DllMain /
C++ ctors initialize before any fused code is used.

No source edits, no C compiler: the object is built with our own coff.py.
The linker wires it in via the `__tls_used` symbol (force with /INCLUDE:__tls_used).

emit_tls_init(entry_symbols, out_path):
    entry_symbols: list of extern names, each a fused DLL's entry (e.g.
                   "_sqlite3_vb6_fzentry"); the callback calls them in order.
"""
from __future__ import annotations
import os
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # dll2lib dir
from coff import (CoffBuilder, FLAGS_TEXT, FLAGS_DATA, FLAGS_RDATA,
                  REL_DIR32, REL_REL32, SYM_TYPE_FUNCTION)


def emit_tls_init(entry_symbols, out_path: str) -> None:
    n = len(entry_symbols)
    if n == 0:
        raise ValueError("no entry symbols")
    if 14 * n > 127:
        raise ValueError("too many init entries for a short jne (add near-jump support)")

    cb = CoffBuilder()
    text = cb.add_section(".text$fz", FLAGS_TEXT)
    rdata = cb.add_section(".rdata$fz", FLAGS_RDATA)
    data = cb.add_section(".data$fz", FLAGS_DATA)
    tls = cb.add_section(".tls", FLAGS_DATA)

    # ---- callback code (.text$fz) ----
    #   push ebp; mov ebp,esp
    #   cmp [ebp+0C],1 (DLL_PROCESS_ATTACH); jne done
    #   per entry: push [ebp+10]; push [ebp+0C]; push [ebp+08]; call entry (stdcall)
    #   done: pop ebp; ret 0C
    code = bytearray([0x55, 0x8B, 0xEC, 0x83, 0x7D, 0x0C, 0x01, 0x75, 14 * n])
    rel32_sites = []
    for _ in range(n):
        code += bytes([0xFF, 0x75, 0x10, 0xFF, 0x75, 0x0C, 0xFF, 0x75, 0x08, 0xE8])
        rel32_sites.append(len(code))            # the rel32 operand offset
        code += b"\x00\x00\x00\x00"
    code += bytes([0x5D, 0xC2, 0x0C, 0x00])      # pop ebp; ret 12
    text.append(bytes(code))

    # ---- TLS template (.tls) ----
    tls.append(b"\x00\x00\x00\x00")

    # ---- TLS index (.data$fz) ----
    data.append(b"\x00\x00\x00\x00")

    # ---- callback array + IMAGE_TLS_DIRECTORY (.rdata$fz) ----
    rdata.append(b"\x00" * 8)                    # cb_array: [ &cb, NULL ]  (off 0)
    rdata.append(b"\x00" * 24)                   # IMAGE_TLS_DIRECTORY32    (off 8)

    # ---- symbols ----
    sym_cb = cb.define("__fz_tls_cb", 0, text.number, SYM_TYPE_FUNCTION)
    sym_start = cb.define("__fz_tls_start", 0, tls.number)
    sym_end = cb.define("__fz_tls_end", 4, tls.number)
    sym_index = cb.define("__fz_tls_index", 0, data.number)
    sym_arr = cb.define("__fz_cb_array", 0, rdata.number)
    cb.define("__tls_used", 8, rdata.number)     # the linker looks for this name
    entry_syms = [cb.extern(e) for e in entry_symbols]

    # ---- relocations ----
    for site, es in zip(rel32_sites, entry_syms):
        cb.reloc(text, site, es, REL_REL32)      # call <entry>
    cb.reloc(rdata, 0, sym_cb, REL_DIR32)        # cb_array[0] = &cb
    cb.reloc(rdata, 8 + 0, sym_start, REL_DIR32)   # StartAddressOfRawData
    cb.reloc(rdata, 8 + 4, sym_end, REL_DIR32)     # EndAddressOfRawData
    cb.reloc(rdata, 8 + 8, sym_index, REL_DIR32)   # AddressOfIndex
    cb.reloc(rdata, 8 + 12, sym_arr, REL_DIR32)    # AddressOfCallBacks
    # SizeOfZeroFill (+16) and Characteristics (+20) stay 0

    with open(out_path, "wb") as f:
        f.write(cb.build())


if __name__ == "__main__":
    # quick self-test: emit an obj for one entry and dump its symbols
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "fztls.obj")
    emit_tls_init(["_test_fzentry"], p)
    print("wrote", p, os.path.getsize(p), "bytes")
