#!/usr/bin/env python3
r"""
exestuff  -  statically fuse a C DLL into a finished VB6 exe (PE surgery).

    exestuff app.exe foo.dll [--out app_stuffed.exe] [--no-tls]

32-bit only. Target exe must be reloc-stripped (VB6 default) so we bake absolute
addresses for its fixed base. Rewrites the `Declare Lib "foo.dll"` thunks to jump
into the stuffed code; no foo.dll at runtime.
"""
from __future__ import annotations
import os
import sys
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pe32 import PE32
import pewrite
from pewrite import PEImage

SKIP = {".rsrc", ".reloc"}
THUNK_SIG = b"\x0B\xC0\x74\x02\xFF\xE0\x68"   # middle of the 25-byte Declare thunk
THUNK_LEN = 25


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


# ---------------------------------------------------------------- DLL image ----
def dll_mapped_blob(dll: PE32, raw: bytes):
    """Flatten the DLL's kept sections into one buffer; return (blob, start)."""
    kept = [s for s in dll.sections if s.name not in SKIP]
    start = min(s.virtual_address for s in kept)
    end = max(s.virtual_address + max(s.virtual_size, s.size_of_raw_data) for s in kept)
    blob = bytearray(end - start)
    for s in kept:
        if getattr(s, "is_bss", False):
            continue
        a = s.pointer_to_raw_data
        d = raw[a:a + s.size_of_raw_data]
        o = s.virtual_address - start
        blob[o:o + len(d)] = d
    return blob, start


def find_thunks(exe: PEImage, dll_name: str):
    """Return [(file_off, thunk_rva, func_name)] for thunks whose Lib == dll_name."""
    data = exe.b
    base = exe.image_base
    want = dll_name.lower()
    out = []
    i = data.find(THUNK_SIG)
    while i != -1:
        t = i - 5
        if t >= 0 and data[t] == 0xA1:
            struct_va = u32(data, i + 7)
            soff = exe.rva_to_off(struct_va - base)
            if soff is not None:
                lib_va, fn_va = struct.unpack_from("<II", data, soff)
                lo = exe.rva_to_off(lib_va - base)
                fo = exe.rva_to_off(fn_va - base)
                if lo is not None and fo is not None:
                    lib = bytes(data[lo:data.index(b"\0", lo)]).decode("latin-1")
                    fn = bytes(data[fo:data.index(b"\0", fo)]).decode("latin-1")
                    if lib.lower() == want:
                        # thunk_rva: t is a file offset in .text
                        for nm, vs, va, rs, rp, _ in exe.sections():
                            if rp <= t < rp + rs:
                                out.append((t, va + (t - rp), fn))
                                break
        i = data.find(THUNK_SIG, i + 1)
    return out


def descriptors(blob_or_img, dir_off, read):
    """Yield (offset, [OFT,TDS,FC,Name,FT]) for each non-null import descriptor."""
    o = dir_off
    while True:
        d = read(o, 20)
        vals = struct.unpack("<IIIII", d)
        if vals == (0, 0, 0, 0, 0):
            break
        yield o, vals
        o += 20


def stuff(exe_path, dll_path, out_path, do_tls=True, do_console=False):
    exe = PEImage(open(exe_path, "rb").read())
    exe_base = exe.image_base
    dll_raw = open(dll_path, "rb").read()
    dll = PE32.from_file(dll_path)
    dll_name = os.path.basename(dll_path)

    if dll.refuse_reasons:
        raise SystemExit("DLL not convertible: %s" % dll.refuse_reasons)

    # --- S2: find the Declare thunks to this DLL ---
    thunks = find_thunks(exe, dll_name)
    if not thunks:
        raise SystemExit("no Declare thunks for %s found in %s" % (dll_name, exe_path))
    print("[S2] thunks: " + ", ".join(f"{fn}" for _, _, fn in thunks))

    # --- S3: build the placeable DLL blob; bake every reloc by a constant delta ---
    blob, start = dll_mapped_blob(dll, dll_raw)
    P1 = exe.next_rva()                       # the blob will land here
    SHIFT = P1 - start                        # exe_rva(dll_rva) = dll_rva + SHIFT
    delta = exe_base - dll.image_base + SHIFT  # add to every HIGHLOW absolute
    stuffed_reloc_rvas = []                     # new RVAs holding baked absolutes
    for r in dll.relocs:
        off = r.rva - start
        if 0 <= off <= len(blob) - 4:
            struct.pack_into("<I", blob, off, (u32(blob, off) + delta) & 0xFFFFFFFF)
            stuffed_reloc_rvas.append(r.rva + SHIFT)
    print(f"[S3] blob {len(blob)} bytes @ rva 0x{P1:X}; baked {len(stuffed_reloc_rvas)} relocs "
          f"(delta=0x{delta & 0xFFFFFFFF:X})")

    # fix the DLL's ILT entries (named-import RVAs) by SHIFT, in the blob
    imp_dir_rva = dll.data_directories[1].rva
    dll_descs = []
    def read_blob(o, n):
        oo = o - start
        return bytes(blob[oo:oo + n])
    for _, (OFT, TDS, FC, Name, FT) in descriptors(blob, imp_dir_rva, read_blob):
        ilt = OFT if OFT else FT
        p = ilt - start
        while True:
            v = u32(blob, p)
            if v == 0:
                break
            if not (v & 0x80000000):          # RVA to IMAGE_IMPORT_BY_NAME
                struct.pack_into("<I", blob, p, v + SHIFT)
            p += 4
        dll_descs.append((OFT, TDS, FC, Name, FT))

    # --- S4: append the DLL blob (RWX) ---
    rva = exe.add_section(".stuff", bytes(blob),
                          pewrite.SCN_CNT_CODE | pewrite.SCN_CNT_INITIALIZED_DATA |
                          pewrite.SCN_MEM_EXECUTE | pewrite.SCN_MEM_READ | pewrite.SCN_MEM_WRITE)
    assert rva == P1, (hex(rva), hex(P1))
    print(f"[S4] appended .stuff at 0x{rva:X}")

    # --- S5: merge the import table (exe descriptors + DLL descriptors) ---
    exe_imp_rva, _ = exe.get_datadir(1)
    merged = b""
    nexe = 0
    for _, vals in descriptors(None, exe_imp_rva, exe.read_rva):
        merged += struct.pack("<IIIII", *vals)
        nexe += 1
    for OFT, TDS, FC, Name, FT in dll_descs:
        merged += struct.pack("<IIIII",
                              (OFT + SHIFT) if OFT else 0, TDS, FC, Name + SHIFT, FT + SHIFT)
    merged += b"\0" * 20
    imp_rva = exe.add_section(".stimp", merged, pewrite.CHARS_RDATA)
    exe.set_datadir(1, imp_rva, len(merged))
    print(f"[S5] merged imports: {nexe} exe + {len(dll_descs)} dll -> .stimp @ 0x{imp_rva:X}")

    # --- S6: rewrite each thunk to `jmp rel32 <export>` + int3 ---
    exports = {e.name: e.rva for e in dll.exports if e.name}
    for file_off, thunk_rva, fn in thunks:
        if fn not in exports:
            raise SystemExit(f"export {fn!r} not found in {dll_name}")
        tgt = exports[fn] + SHIFT
        rel = (tgt - (thunk_rva + 5)) & 0xFFFFFFFF
        patch = b"\xE9" + struct.pack("<I", rel) + b"\xCC" * (THUNK_LEN - 5)
        exe.b[file_off:file_off + THUNK_LEN] = patch
    print(f"[S6] rewrote {len(thunks)} thunks -> jmp into .stuff")

    # --- S7: inject a TLS callback that runs the DLL's entry (CRT/DllMain) ---
    tls_va_rvas = []
    if do_tls and dll.address_of_entry_point:
        tls_va_rvas = inject_tls(exe, dll.address_of_entry_point + SHIFT)
        print("[S7] TLS callback -> DLL entry (CRT init)")

    # --- reloc merge: if the target is relocatable (ActiveX DLL/exe has a
    #     .reloc), the baked absolutes (stuffed code + TLS VA fields) must move
    #     under ASLR -- add their HIGHLOW entries to the target's base-reloc
    #     table. (A reloc-stripped VB6 exe is fixed-base: nothing to do.)
    if exe.get_datadir(5)[1]:
        rvas = stuffed_reloc_rvas + tls_va_rvas
        expand_relocs(exe, rvas)
        print(f"[reloc] target is relocatable -> expanded .reloc with {len(rvas)} entries")

    if do_console:
        exe.set_subsystem(3)                  # CONSOLE: a ConsolePrint Sub reaches stdout
        print("[--console] subsystem -> console")

    open(out_path, "wb").write(exe.to_bytes())
    print(f"\nSTUFFED -> {out_path}  ({os.path.getsize(out_path)} bytes); no {dll_name} needed")


def inject_tls(exe: PEImage, entry_rva: int):
    """Append a .sttls section with a TLS directory + one callback that forwards
    (hinst, reason, reserved) to entry_rva on DLL_PROCESS_ATTACH."""
    base = exe.image_base
    P = exe.next_rva()
    # Forward ALL reasons (ATTACH/THREAD_*/DETACH) to DllMainCRTStartup, exactly
    # like a real DLL entry. DETACH matters: that's when the CRT does FlsFree to
    # unregister its FLS callback -- skip it and ntdll calls the dangling callback
    # into the (by-then unmapped) stuffed region at process teardown -> crash.
    #   0: 55            push ebp
    #   1: 8B EC         mov ebp,esp
    #   3: FF 75 10      push [ebp+10]          ; reserved
    #   6: FF 75 0C      push [ebp+0C]          ; reason
    #   9: FF 75 08      push [ebp+08]          ; hinst
    #   C: E8 <rel32>    call entry             ; operand at D, ends at 11
    #  11: 5D            pop ebp
    #  12: C2 0C 00      ret 0C
    stub = bytearray(b"\x55\x8B\xEC"
                     b"\xFF\x75\x10\xFF\x75\x0C\xFF\x75\x08\xE8\x00\x00\x00\x00"
                     b"\x5D\xC2\x0C\x00")
    call_site = 12                               # offset of E8
    idx_off = _align4 = (len(stub) + 3) & ~3     # 4-align the data that follows
    tmpl_off = idx_off + 4
    cbarr_off = tmpl_off + 4
    dir_off = cbarr_off + 8
    buf = bytearray(stub) + b"\0" * (dir_off + 24 - len(stub))

    # call rel32 -> entry: rel = target - (addr_after_instruction)
    call_rva = P + call_site
    struct.pack_into("<i", buf, call_site + 1, entry_rva - (call_rva + 5))
    # callback array: [VA(stub), 0]
    struct.pack_into("<II", buf, cbarr_off, base + P + 0, 0)
    # IMAGE_TLS_DIRECTORY32: Start,End,AddrIndex,AddrCallbacks,SizeOfZeroFill,Chars
    struct.pack_into("<IIIIII", buf, dir_off,
                     base + P + tmpl_off, base + P + tmpl_off + 4,
                     base + P + idx_off, base + P + cbarr_off, 0, 0)

    rva = exe.add_section(".sttls", bytes(buf),
                          pewrite.SCN_CNT_INITIALIZED_DATA | pewrite.SCN_MEM_EXECUTE |
                          pewrite.SCN_MEM_READ | pewrite.SCN_MEM_WRITE)
    exe.set_datadir(9, rva + dir_off, 24)   # IMAGE_DIRECTORY_ENTRY_TLS
    # the absolute VA fields (for a relocatable target, these need base relocs)
    return [rva + cbarr_off,                # callback array[0] = &stub
            rva + dir_off + 0,              # StartAddressOfRawData
            rva + dir_off + 4,              # EndAddressOfRawData
            rva + dir_off + 8,              # AddressOfIndex
            rva + dir_off + 12]             # AddressOfCallBacks


def expand_relocs(exe: PEImage, rvas):
    """Append the target's existing base-reloc table + new HIGHLOW entries for
    `rvas` as a fresh `.streloc` section, and repoint the base-reloc data dir."""
    from collections import defaultdict
    rva0, size0 = exe.get_datadir(5)
    existing = exe.read_rva(rva0, size0) if size0 else b""
    pages = defaultdict(list)
    for r in rvas:
        pages[r & ~0xFFF].append(r & 0xFFF)
    blocks = b""
    for page in sorted(pages):
        ents = b"".join(struct.pack("<H", 0x3000 | o) for o in sorted(pages[page]))
        if len(ents) % 4:                   # DWORD-align the block with an ABSOLUTE(0) pad
            ents += b"\x00\x00"
        blocks += struct.pack("<II", page, 8 + len(ents)) + ents
    merged = existing + blocks
    nrva = exe.add_section(".streloc", merged, pewrite.CHARS_RDATA)
    exe.set_datadir(5, nrva, len(merged))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="exestuff")
    ap.add_argument("exe")
    ap.add_argument("dll")
    ap.add_argument("--out")
    ap.add_argument("--no-tls", action="store_true")
    ap.add_argument("--console", action="store_true",
                    help="set the stuffed exe's subsystem to CONSOLE so a VB "
                         "ConsolePrint-style Sub reaches stdout (handy for testing)")
    a = ap.parse_args(argv)
    out = a.out or (os.path.splitext(a.exe)[0] + "_stuffed.exe")
    stuff(a.exe, a.dll, out, do_tls=not a.no_tls, do_console=a.console)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
