"""
coff.py  -  hand-rolled i386 COFF object (.obj) writer for dll2lib.

STAGE S1. This is THE product: the converter's output COFF must be built by
us, byte for byte, then handed to MS lib.exe to wrap into a .lib. The layout
and conventions here mirror VBStatic.bas's battle-tested BuildObjFile (symbol
record form, zeroed-then-patched section-symbol aux, the NRELOC_OVFL trick,
the 4-byte string-table size prefix).

COFF object file layout we emit:
    IMAGE_FILE_HEADER (20)
    IMAGE_SECTION_HEADER * nsec (40 each)
    [ per section: raw data (pad4), then relocations (pad4) ]
    symbol table (18 per record; section symbols carry one 18-byte aux)
    string table (4-byte total-size prefix + null-terminated long names)
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field

MACHINE_I386 = 0x014C

# IMAGE_SCN_* section characteristics
SCN_CNT_CODE = 0x00000020
SCN_CNT_INITIALIZED_DATA = 0x00000040
SCN_CNT_UNINITIALIZED_DATA = 0x00000080
SCN_LNK_INFO = 0x00000200
SCN_LNK_REMOVE = 0x00000800
SCN_LNK_NRELOC_OVFL = 0x01000000
SCN_ALIGN_1 = 0x00100000
SCN_ALIGN_2 = 0x00200000
SCN_ALIGN_4 = 0x00300000
SCN_ALIGN_8 = 0x00400000
SCN_ALIGN_16 = 0x00500000
SCN_MEM_DISCARDABLE = 0x02000000
SCN_MEM_EXECUTE = 0x20000000
SCN_MEM_READ = 0x40000000
SCN_MEM_WRITE = 0x80000000

# common combinations
# 16-byte alignment on data sections preserves SSE-aligned constants/structs
# whose intra-section offset was 16-aligned in the original image; over-aligning
# is always safe (costs at most a few padding bytes). AVX-512 (64B) data is not
# guaranteed -- see the compatibility notes.
FLAGS_TEXT = SCN_CNT_CODE | SCN_ALIGN_16 | SCN_MEM_EXECUTE | SCN_MEM_READ
FLAGS_DATA = SCN_CNT_INITIALIZED_DATA | SCN_ALIGN_16 | SCN_MEM_READ | SCN_MEM_WRITE
FLAGS_RDATA = SCN_CNT_INITIALIZED_DATA | SCN_ALIGN_16 | SCN_MEM_READ
FLAGS_BSS = SCN_CNT_UNINITIALIZED_DATA | SCN_ALIGN_16 | SCN_MEM_READ | SCN_MEM_WRITE

# IMAGE_SYM_CLASS_*
SYM_CLASS_EXTERNAL = 2
SYM_CLASS_STATIC = 3
SYM_CLASS_LABEL = 6

# symbol complex type: function = DTYPE(2) << 4
SYM_TYPE_NULL = 0x00
SYM_TYPE_FUNCTION = 0x20

# IMAGE_REL_I386_*
REL_DIR32 = 0x0006
REL_DIR32NB = 0x0007
REL_REL32 = 0x0014


class CoffError(Exception):
    pass


@dataclass
class _Reloc:
    va: int
    sym: int
    typ: int


@dataclass
class Section:
    name: str
    flags: int
    number: int                      # 1-based section index
    data: bytearray = field(default_factory=bytearray)
    relocs: list[_Reloc] = field(default_factory=list)
    bss: int = 0                     # size if uninitialized (no raw data)
    sym_index: int = -1              # index of this section's STATIC symbol

    def append(self, b: bytes) -> int:
        """Append raw bytes, returning the offset they were placed at."""
        off = len(self.data)
        self.data += b
        return off

    @property
    def size(self) -> int:
        return self.bss if self.bss > 0 else len(self.data)


class CoffBuilder:
    def __init__(self, machine: int = MACHINE_I386):
        self.machine = machine
        self.sections: list[Section] = []
        self._symtab = bytearray()
        self._symN = 0
        self._strtab = bytearray(b"\x00\x00\x00\x00")  # reserve the size prefix
        self._have: dict[str, int] = {}
        self._sec_sym_patches: list[tuple[int, Section]] = []

    # ---------- sections ----------
    def add_section(self, name: str, flags: int, bss: int = 0,
                    with_symbol: bool = True) -> Section:
        num = len(self.sections) + 1
        sec = Section(name=name, flags=flags, number=num, bss=bss)
        self.sections.append(sec)
        # Most sections get a STATIC section symbol with an aux record, patched
        # with length + reloc-count at build time. Info sections (.drectve) skip
        # it (with_symbol=False).
        if with_symbol:
            sec.sym_index = self.add_symbol(name, 0, num, 0, SYM_CLASS_STATIC, aux=True)
            self._sec_sym_patches.append((sec.sym_index, sec))
        return sec

    def reloc(self, sec: Section, va: int, sym: int, typ: int) -> None:
        sec.relocs.append(_Reloc(va, sym, typ))

    # ---------- symbols ----------
    def add_symbol(self, name: str, value: int, sec: int, typ: int,
                   cls: int, aux: bool = False) -> int:
        idx = self._symN
        self._have[name] = idx
        nb = name.encode("latin-1")
        if len(nb) <= 8:
            self._symtab += nb + b"\x00" * (8 - len(nb))
        else:
            self._symtab += struct.pack("<II", 0, len(self._strtab))
            self._strtab += nb + b"\x00"
        self._symtab += struct.pack("<IhHB", value & 0xFFFFFFFF, sec, typ, cls)
        self._symtab += bytes([1 if aux else 0])
        self._symN += 1
        if aux:
            self._symtab += b"\x00" * 18
            self._symN += 1
        return idx

    def extern(self, name: str) -> int:
        """Reference a global: reuse our own symbol if defined, else a new undef external."""
        if name in self._have:
            return self._have[name]
        return self.add_symbol(name, 0, 0, SYM_TYPE_NULL, SYM_CLASS_EXTERNAL)

    def define(self, name: str, value: int, sec_number: int,
               typ: int = SYM_TYPE_NULL) -> int:
        """Define a global symbol; fill an existing undef entry in place if present."""
        if name in self._have:
            i = self._have[name]
            o = i * 18
            cur_cls = self._symtab[o + 16]
            cur_val = struct.unpack_from("<I", self._symtab, o + 8)[0]
            cur_sec = struct.unpack_from("<h", self._symtab, o + 12)[0]
            if not (cur_cls == SYM_CLASS_EXTERNAL and cur_val == 0 and cur_sec == 0):
                raise CoffError(f"duplicate definition of symbol {name!r}")
            struct.pack_into("<I", self._symtab, o + 8, value & 0xFFFFFFFF)
            struct.pack_into("<h", self._symtab, o + 12, sec_number)
            struct.pack_into("<H", self._symtab, o + 14, typ)
            return i
        return self.add_symbol(name, value, sec_number, typ, SYM_CLASS_EXTERNAL)

    # ---------- serialize ----------
    def build(self) -> bytes:
        # 1) NRELOC_OVFL: sections with > 0xFFFF relocs get a leading dummy
        #    reloc carrying the true count, and the overflow flag set.
        for sec in self.sections:
            if len(sec.relocs) > 0xFFFF and not (sec.flags & SCN_LNK_NRELOC_OVFL):
                n = len(sec.relocs)
                sec.relocs.insert(0, _Reloc(n + 1, 0, 0))
                sec.flags |= SCN_LNK_NRELOC_OVFL

        # 2) patch each section symbol's aux: Length + NumberOfRelocations
        for sym_idx, sec in self._sec_sym_patches:
            o = sym_idx * 18 + 18           # start of the aux record
            struct.pack_into("<I", self._symtab, o, sec.size)
            rc = 0xFFFF if (sec.flags & SCN_LNK_NRELOC_OVFL) else len(sec.relocs)
            struct.pack_into("<H", self._symtab, o + 4, rc)

        nsec = len(self.sections)
        hdr = 20 + 40 * nsec
        body = bytearray()
        heads = bytearray()

        for sec in self.sections:
            dp = 0
            rp = 0
            if len(sec.data) > 0:
                dp = hdr + len(body)
                body += sec.data
                _pad4(body)
            if len(sec.relocs) > 0:
                rp = hdr + len(body)
                for r in sec.relocs:
                    body += struct.pack("<IIH", r.va, r.sym, r.typ)
                _pad4(body)

            nb = sec.name.encode("latin-1")
            heads += nb[:8] + b"\x00" * (8 - min(len(nb), 8))
            heads += struct.pack("<I", 0)              # VirtualSize (0 in objs)
            heads += struct.pack("<I", 0)              # VirtualAddress
            heads += struct.pack("<I", sec.size)       # SizeOfRawData
            heads += struct.pack("<I", dp)             # PointerToRawData
            heads += struct.pack("<I", rp)             # PointerToRelocations
            heads += struct.pack("<I", 0)              # PointerToLinenumbers
            nrel = 0xFFFF if (sec.flags & SCN_LNK_NRELOC_OVFL) else len(sec.relocs)
            heads += struct.pack("<H", nrel)           # NumberOfRelocations
            heads += struct.pack("<H", 0)              # NumberOfLinenumbers
            heads += struct.pack("<I", sec.flags)      # Characteristics

        out = bytearray()
        # IMAGE_FILE_HEADER
        out += struct.pack("<HH", self.machine, nsec)
        out += struct.pack("<I", 0)                    # TimeDateStamp
        out += struct.pack("<I", hdr + len(body))      # PointerToSymbolTable
        out += struct.pack("<I", self._symN)           # NumberOfSymbols
        out += struct.pack("<HH", 0, 0)                # SizeOfOptionalHeader, Characteristics
        out += heads
        out += body
        out += self._symtab
        # string table: patch total size into its 4-byte prefix
        struct.pack_into("<I", self._strtab, 0, len(self._strtab))
        out += self._strtab
        return bytes(out)


def _pad4(buf: bytearray) -> None:
    if len(buf) & 3:
        buf += b"\x00" * (4 - (len(buf) & 3))
