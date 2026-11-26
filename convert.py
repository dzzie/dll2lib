"""
convert.py  -  turn a parsed PE32 DLL into a static COFF object (dll2lib core).

STAGE S2 (spine). Implements the minimal end-to-end conversion:
  * carry the DLL's sections (except .reloc, which we consume; .rsrc skipped v1)
    into COFF sections;
  * convert every HIGHLOW base relocation into a COFF DIR32 relocation -- the
    stored absolute value is rewritten to an OFFSET inside the target section,
    and the relocation's symbol is that target section's symbol;
  * emit each named export as `_<name>` pointing at its section+offset.

Not yet handled (later stages): import rebuild (S4), __imp__ slots + stdcall
decoration (S3), the section-merge rule for multi-code-section DLLs (S7),
DllMain/CRT bootstrap (S6), TLS/resources (S7). Callers should check
pe.is_convertible / pe.refuse_reasons first.
"""
from __future__ import annotations
import struct

import struct as _struct

from pe32 import PE32, DIR_IAT
from coff import (CoffBuilder, FLAGS_TEXT, FLAGS_DATA, FLAGS_RDATA, FLAGS_BSS,
                  REL_DIR32, REL_DIR32NB, SYM_TYPE_FUNCTION, SYM_TYPE_NULL,
                  SCN_CNT_CODE, SCN_MEM_WRITE)

# sections we never carry: .reloc is consumed; .rsrc deferred to v2.
SKIP_SECTIONS = {".reloc", ".rsrc"}

# .idata$* fragments: initialized data, 4-byte aligned, read/write (the loader
# writes resolved addresses into the IAT).
FLAGS_IDATA = 0xC0300040


def _iat_range(pe: PE32) -> tuple[int, int]:
    """(rva, size) of the IAT: the IAT data directory, widened to cover every
    import thunk (+ its null terminator) so slot offsets are always in range."""
    iat_rva, iat_sz = 0, 0
    if DIR_IAT < len(pe.data_directories):
        d = pe.data_directories[DIR_IAT]
        iat_rva, iat_sz = d.rva, d.size
    thunks = [t.iat_rva for imp in pe.imports for t in imp.thunks]
    if not thunks:
        return iat_rva, iat_sz
    lo, hi = min(thunks), max(thunks) + 8      # +4 slot, +4 for the null terminator
    if iat_rva == 0:
        iat_rva = lo
    end = max(iat_rva + iat_sz, hi)
    return iat_rva, end - iat_rva


def _rebuild_imports(cb: CoffBuilder, pe: PE32, iat_rva: int, iat_sz: int):
    """Rebuild the DLL's own import table as .idata$2/$3/$4/$5/$6 so link.exe
    produces the final exe's import directory. Returns the .idata$5 (IAT)
    section, whose slots the DLL's redirected code references. $4/$5 mirror the
    original IAT layout (slot offset = thunk.iat_rva - iat_rva)."""
    n = len(pe.imports)
    sD2 = cb.add_section(".idata$2", FLAGS_IDATA); sD2.append(b"\x00" * (20 * n))
    sD3 = cb.add_section(".idata$3", FLAGS_IDATA); sD3.append(b"\x00" * 20)   # terminator
    sD4 = cb.add_section(".idata$4", FLAGS_IDATA); sD4.append(b"\x00" * iat_sz)
    sD5 = cb.add_section(".idata$5", FLAGS_IDATA); sD5.append(b"\x00" * iat_sz)
    sD6 = cb.add_section(".idata$6", FLAGS_IDATA)

    def put_hintname(hint: int, name: str) -> int:
        off = len(sD6.data)
        sD6.append(_struct.pack("<H", hint & 0xFFFF))
        sD6.append(name.encode("latin-1") + b"\x00")
        if len(sD6.data) & 1:
            sD6.append(b"\x00")
        return off

    name_off = []
    for imp in pe.imports:
        name_off.append(len(sD6.data))
        sD6.append(imp.name.encode("latin-1") + b"\x00")
        if len(sD6.data) & 1:
            sD6.append(b"\x00")

    for d, imp in enumerate(pe.imports):
        base = imp.first_thunk - iat_rva          # this DLL's thunk array offset in $4/$5
        for t in imp.thunks:
            o = t.iat_rva - iat_rva
            if t.by_ordinal:
                val = 0x80000000 | (t.ordinal & 0xFFFF)
                _struct.pack_into("<I", sD4.data, o, val)
                _struct.pack_into("<I", sD5.data, o, val)
            else:
                ho = put_hintname(t.hint or 0, t.name)
                _struct.pack_into("<I", sD4.data, o, ho)
                _struct.pack_into("<I", sD5.data, o, ho)
                cb.reloc(sD4, o, sD6.sym_index, REL_DIR32NB)
                cb.reloc(sD5, o, sD6.sym_index, REL_DIR32NB)
        od = 20 * d
        _struct.pack_into("<I", sD2.data, od + 0, base)             # OriginalFirstThunk
        _struct.pack_into("<I", sD2.data, od + 12, name_off[d])     # Name
        _struct.pack_into("<I", sD2.data, od + 16, base)            # FirstThunk
        cb.reloc(sD2, od + 0, sD4.sym_index, REL_DIR32NB)
        cb.reloc(sD2, od + 12, sD6.sym_index, REL_DIR32NB)
        cb.reloc(sD2, od + 16, sD5.sym_index, REL_DIR32NB)
    return sD5


class ConvertError(Exception):
    pass


def _coff_flags(ps) -> int:
    if ps.is_code:
        return FLAGS_TEXT
    if ps.is_bss:
        return FLAGS_BSS
    writable = bool(ps.characteristics & SCN_MEM_WRITE)
    return FLAGS_DATA if writable else FLAGS_RDATA


def _secname(name: str) -> str:
    # COFF section names are <= 8 chars; long names need a /offset form we
    # don't emit yet. Spine DLLs use short names; guard loudly otherwise.
    if len(name.encode("latin-1")) > 8:
        raise ConvertError(f"section name {name!r} > 8 chars (long-name COFF form not implemented)")
    return name


def convert(pe: PE32, stdcall_args: dict[str, int] | None = None,
            init_symbol: str | None = None, entry_symbol: str | None = None) -> bytes:
    """Convert a parsed PE32 DLL to a COFF object.

    stdcall_args maps an export name to its __stdcall arg-byte count; for each,
    we additionally emit the DECORATED symbols `_Name@n` / `__imp__Name@n` as
    real definitions (same body / same slot) so stdcall consumers resolve them
    straight from the lib's archive index -- not via fragile .drectve aliases,
    which only fire once the object is already pulled into the link.

    init_symbol, if given, emits a bootstrap function of that name which the
    consumer MUST call once before using any export: it invokes the DLL's
    original entry point as DllMain(&__ImageBase, DLL_PROCESS_ATTACH, 0) so the
    CRT / DllMain / C++ global ctors run. (No-op `ret` if the DLL has no entry.)
    """
    stdcall_args = stdcall_args or {}
    if pe.refuse_reasons:
        raise ConvertError("DLL is not convertible: " + "; ".join(pe.refuse_reasons))

    cb = CoffBuilder()

    def mapped(ps) -> bytes:
        # the MAPPED image bytes (virtual_size): zero-extend a bss tail
        # (virtual_size > raw), drop file-alignment padding (raw > virtual_size).
        data = bytes(ps.raw)
        vs = ps.virtual_size
        if vs:
            data = data[:vs] if vs <= len(data) else data + b"\x00" * (vs - len(data))
        return data

    # regions: (start_rva, end_rva, coff_section, base_rva); offset = rva - base
    regions: list[tuple[int, int, object, int]] = []
    kept = [ps for ps in pe.sections if ps.name not in SKIP_SECTIONS]
    code_secs = [ps for ps in kept if ps.is_code]

    # Section-merge rule: >1 code section must become ONE contiguous .text so
    # inter-section rel32 branches (which carry no base reloc) keep their
    # displacements. Layout mirrors the original (slot = va - cbase), gaps
    # zero-filled; this is why dead-code elimination is impossible.
    merged_code = len(code_secs) >= 2
    if merged_code:
        cbase = min(ps.virtual_address for ps in code_secs)
        cend = max(ps.virtual_address + max(ps.virtual_size, ps.size_of_raw_data)
                   for ps in code_secs)
        merged = cb.add_section(".text", FLAGS_TEXT)
        buf = bytearray(cend - cbase)
        for ps in code_secs:
            d = mapped(ps)
            o = ps.virtual_address - cbase
            buf[o:o + len(d)] = d
        merged.append(bytes(buf))
        regions.append((cbase, cend, merged, cbase))

    for ps in kept:
        if merged_code and ps.is_code:
            continue
        flags = _coff_flags(ps)
        if ps.is_bss:
            cs = cb.add_section(_secname(ps.name), flags, bss=max(ps.virtual_size, 1))
        else:
            cs = cb.add_section(_secname(ps.name), flags)
            cs.append(mapped(ps))
        end = ps.virtual_address + max(ps.virtual_size, ps.size_of_raw_data)
        regions.append((ps.virtual_address, end, cs, ps.virtual_address))

    lowest_va = min((st for st, _, _, _ in regions), default=0)

    def find(rva: int):
        for st, en, cs, base in regions:
            if st <= rva < en:
                return cs, rva - base
        return None, 0

    # --- rebuild the DLL's own imports as .idata$* (S4) ---
    iat_rva, iat_sz = _iat_range(pe)
    idata5 = _rebuild_imports(cb, pe, iat_rva, iat_sz) if pe.imports else None

    # --- HIGHLOW base relocs -> COFF DIR32 ---
    for r in pe.relocs:                      # parser already dropped ABSOLUTE padding
        cs, off = find(r.rva)
        if cs is None:
            continue                         # reloc inside a skipped section
        if off + 4 > len(cs.data):
            continue                         # in a bss tail we didn't carry
        stored = struct.unpack_from("<I", cs.data, off)[0]
        target_rva = (stored - pe.image_base) & 0xFFFFFFFF
        if idata5 is not None and iat_rva <= target_rva < iat_rva + iat_sz:
            # a code/data reference to an IAT slot -> redirect to rebuilt .idata$5
            tsym = idata5.sym_index
            addend = target_rva - iat_rva
        else:
            tcs, toff = find(target_rva)
            if tcs is not None:
                tsym = tcs.sym_index
                addend = toff
            elif target_rva < lowest_va:
                # pointer into the PE headers / image base (e.g. the CRT storing
                # the module handle); rebase onto the fused exe's own image base.
                tsym = cb.extern("___ImageBase")
                addend = target_rva
            else:
                raise ConvertError(
                    f"reloc at RVA 0x{r.rva:X} targets 0x{target_rva:X}, "
                    f"outside carried sections")
        struct.pack_into("<I", cs.data, off, addend & 0xFFFFFFFF)
        cb.reloc(cs, off, tsym, REL_DIR32)

    # --- exports -> `_<name>` (body) + `__imp__<name>` (slot -> body) ---
    # The .imp section holds one 4-byte pointer slot per export so consumers
    # built with __declspec(dllimport) (call-through-pointer) link too.
    exports = [e for e in pe.exports if e.forwarder is None and e.rva != 0]
    impsec = cb.add_section(".imp", FLAGS_RDATA) if exports else None
    for e in exports:
        cs, off = find(e.rva)
        if cs is None:
            continue
        name = e.name if e.name is not None else f"ordinal{e.ordinal}"
        typ = SYM_TYPE_FUNCTION if (cs.flags & SCN_CNT_CODE) else SYM_TYPE_NULL
        fn = "_" + name
        fnsym = cb.define(fn, off, cs.number, typ)
        # __imp__<name>: a data slot pointing (DIR32) at the body symbol
        slot = impsec.append(b"\x00\x00\x00\x00")
        cb.reloc(impsec, slot, fnsym, REL_DIR32)
        cb.define("__imp_" + fn, slot, impsec.number)
        # decorated stdcall aliases as REAL definitions (land in the lib index)
        n = stdcall_args.get(name)
        if n is not None:
            fn_d = f"_{name}@{n}"
            cb.define(fn_d, off, cs.number, typ)
            cb.define("__imp_" + fn_d, slot, impsec.number)

    # --- expose the DLL's original entry (DllMainCRTStartup) as a symbol so an
    # external initializer (e.g. a TLS callback) can run the CRT/DllMain. ---
    if entry_symbol and pe.address_of_entry_point:
        ecs, eoff = find(pe.address_of_entry_point)
        if ecs is None:
            raise ConvertError("entry point RVA not in a carried section")
        cb.define(entry_symbol, eoff, ecs.number, SYM_TYPE_FUNCTION)

    # --- DllMain/CRT bootstrap (S6) ---
    if init_symbol:
        _emit_bootstrap(cb, pe, find, init_symbol)

    return cb.build()


def _emit_bootstrap(cb: CoffBuilder, pe: PE32, find, init_symbol: str) -> None:
    binit = cb.add_section(".binit", FLAGS_TEXT)
    ep = pe.address_of_entry_point
    if not ep:
        binit.append(b"\xC3")                        # no entry -> StaticInit is a no-op
        cb.define(init_symbol, 0, binit.number, SYM_TYPE_FUNCTION)
        return
    epc, ep_off = find(ep)
    if epc is None:
        raise ConvertError("entry point RVA not in a carried section")
    code = bytearray()
    code += bytes([0x6A, 0x00, 0x6A, 0x01, 0x68])    # push 0; push 1; push imm32
    code += b"\x00\x00\x00\x00"                        # off 5: hinstDLL = &__ImageBase
    code += bytes([0xB8])                              # mov eax, imm32
    code += _struct.pack("<I", ep_off)                # off 10: entry (code + ep_off)
    code += bytes([0xFF, 0xD0, 0xC3])                 # call eax; ret  (entry is stdcall, cleans 12)
    binit.append(bytes(code))
    # x86 COFF name for the linker-provided image-base symbol is ___ImageBase
    # (C identifier __ImageBase + the usual leading-underscore decoration).
    cb.reloc(binit, 5, cb.extern("___ImageBase"), REL_DIR32)
    cb.reloc(binit, 10, epc.sym_index, REL_DIR32)
    cb.define(init_symbol, 0, binit.number, SYM_TYPE_FUNCTION)
