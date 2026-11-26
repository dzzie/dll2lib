"""
pe32.py  -  dependency-free PE32 (i386) reader for dll2lib.

STAGE S0. Parses the parts of a PE32 DLL that the converter needs:
DOS/PE headers, optional header + data directories, section table,
export directory, import descriptors, and base relocations. Validates
that the image is i386 PE32 with a usable .reloc, and collects the
reasons a DLL would be REFUSED for conversion (no relocs, bound
imports, TLS, non-i386, PE32+).

Input parsing only -- this is the oracle our own COFF writer (S1+) is
checked against. We roll our own (no pefile) so later stages have
byte-exact offsets and raw section data under our control.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field

# ---- machine / magic constants ----
IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_NT_OPTIONAL_HDR32_MAGIC = 0x010B
IMAGE_NT_OPTIONAL_HDR64_MAGIC = 0x020B

# ---- IMAGE_FILE_HEADER.Characteristics bits we care about ----
IMAGE_FILE_RELOCS_STRIPPED = 0x0001
IMAGE_FILE_DLL = 0x2000
IMAGE_FILE_32BIT_MACHINE = 0x0100

# ---- data directory indices ----
DIR_EXPORT = 0
DIR_IMPORT = 1
DIR_RESOURCE = 2
DIR_BASERELOC = 5
DIR_TLS = 9
DIR_BOUND_IMPORT = 11
DIR_IAT = 12
DIR_DELAY_IMPORT = 13

# ---- base relocation types ----
IMAGE_REL_BASED_ABSOLUTE = 0
IMAGE_REL_BASED_HIGHLOW = 3
IMAGE_REL_BASED_DIR64 = 10

_RELOC_TYPE_NAMES = {0: "ABSOLUTE", 1: "HIGH", 2: "LOW", 3: "HIGHLOW",
                     4: "HIGHADJ", 10: "DIR64"}


class PEError(Exception):
    """Fatal: the bytes are not a PE we can parse at all."""


@dataclass
class Section:
    name: str
    virtual_size: int
    virtual_address: int        # RVA
    size_of_raw_data: int
    pointer_to_raw_data: int     # file offset
    characteristics: int
    raw: bytes = b""            # the section's raw bytes (as in file)

    @property
    def is_code(self) -> bool:
        return bool(self.characteristics & 0x00000020)  # CNT_CODE

    @property
    def is_bss(self) -> bool:
        return bool(self.characteristics & 0x00000080)  # CNT_UNINITIALIZED_DATA


@dataclass
class ExportEntry:
    ordinal: int                 # biased ordinal (Base + index)
    rva: int                     # 0 if this ordinal slot is empty
    name: str | None             # None for by-ordinal-only exports
    forwarder: str | None = None  # "OTHER.Func" if this is a forwarder


@dataclass
class ImportThunk:
    by_ordinal: bool
    ordinal: int | None
    hint: int | None
    name: str | None
    iat_rva: int                 # RVA of the IAT slot for this symbol


@dataclass
class ImportDll:
    name: str
    original_first_thunk: int    # ILT RVA (0 => none; use FirstThunk)
    first_thunk: int             # IAT RVA
    time_date_stamp: int
    forwarder_chain: int
    bound: bool
    thunks: list[ImportThunk] = field(default_factory=list)


@dataclass
class DelayImportDll:
    name: str
    count: int                   # INT entry count
    attrs: int                   # grAttrs (bit0 = RVAs, else VAs)


@dataclass
class RelocEntry:
    rva: int                     # absolute RVA this fixup sits at
    type: int                    # IMAGE_REL_BASED_*


@dataclass
class DataDirectory:
    rva: int
    size: int


class PE32:
    def __init__(self, data: bytes, path: str | None = None):
        self.data = data
        self.path = path
        # headers
        self.e_lfanew = 0
        self.machine = 0
        self.number_of_sections = 0
        self.characteristics = 0
        self.size_of_optional_header = 0
        self.opt_magic = 0
        self.address_of_entry_point = 0
        self.image_base = 0
        self.section_alignment = 0
        self.file_alignment = 0
        self.size_of_image = 0
        self.size_of_headers = 0
        self.subsystem = 0
        self.number_of_rva_and_sizes = 0
        self.data_directories: list[DataDirectory] = []
        self.sections: list[Section] = []
        self.exports: list[ExportEntry] = []
        self.export_dll_name: str | None = None
        self.imports: list[ImportDll] = []
        self.delay_imports: list[DelayImportDll] = []
        self.relocs: list[RelocEntry] = []
        self.reloc_type_counts: dict[int, int] = {}
        self.has_tls = False
        self.refuse_reasons: list[str] = []
        self._parse()

    # ---------- low-level helpers ----------
    def _u16(self, off: int) -> int:
        return struct.unpack_from("<H", self.data, off)[0]

    def _u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.data, off)[0]

    def rva_to_off(self, rva: int) -> int | None:
        """Map an RVA to a file offset using the section table."""
        for s in self.sections:
            if s.size_of_raw_data == 0:
                continue
            start = s.virtual_address
            end = s.virtual_address + max(s.virtual_size, s.size_of_raw_data)
            if start <= rva < end:
                delta = rva - s.virtual_address
                if delta < s.size_of_raw_data:
                    return s.pointer_to_raw_data + delta
                return None  # in a bss tail, no raw bytes
        # headers region
        if rva < self.size_of_headers:
            return rva
        return None

    def _cstr(self, off: int, limit: int = 4096) -> str:
        if off is None or off < 0 or off >= len(self.data):
            return ""
        end = self.data.find(b"\x00", off, off + limit)
        if end < 0:
            end = min(off + limit, len(self.data))
        return self.data[off:end].decode("latin-1")

    def _cstr_rva(self, rva: int) -> str:
        off = self.rva_to_off(rva)
        return self._cstr(off) if off is not None else ""

    def in_dir(self, rva: int, which: int) -> bool:
        if which >= len(self.data_directories):
            return False
        d = self.data_directories[which]
        return d.rva <= rva < d.rva + d.size

    # ---------- parse ----------
    def _parse(self):
        d = self.data
        if len(d) < 0x40 or d[0:2] != b"MZ":
            raise PEError("not an MZ/DOS image")
        self.e_lfanew = self._u32(0x3C)
        if self.e_lfanew + 24 > len(d) or d[self.e_lfanew:self.e_lfanew + 4] != b"PE\x00\x00":
            raise PEError("no PE signature at e_lfanew")

        fh = self.e_lfanew + 4                      # IMAGE_FILE_HEADER
        (self.machine, self.number_of_sections, _tds, _psym, _nsym,
         self.size_of_optional_header, self.characteristics) = struct.unpack_from("<HHIIIHH", d, fh)

        opt = fh + 20                                # IMAGE_OPTIONAL_HEADER
        self.opt_magic = self._u16(opt)
        if self.machine != IMAGE_FILE_MACHINE_I386:
            self.refuse_reasons.append(
                f"machine 0x{self.machine:04X} is not i386 (0x14C); x64/ARM out of scope")
        if self.opt_magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC:
            self.refuse_reasons.append("PE32+ (64-bit) image; v1 is PE32/i386 only")
            # bail on 64-bit layout -- the rest of this parser assumes PE32 offsets
            self._parse_sections(opt)
            self._finalize_refusals()
            return
        if self.opt_magic != IMAGE_NT_OPTIONAL_HDR32_MAGIC:
            raise PEError(f"unknown optional header magic 0x{self.opt_magic:04X}")

        self.address_of_entry_point = self._u32(opt + 16)
        self.base_of_code = self._u32(opt + 20)
        self.image_base = self._u32(opt + 28)
        self.section_alignment = self._u32(opt + 32)
        self.file_alignment = self._u32(opt + 36)
        self.size_of_image = self._u32(opt + 56)
        self.size_of_headers = self._u32(opt + 60)
        self.subsystem = self._u16(opt + 68)
        self.number_of_rva_and_sizes = self._u32(opt + 92)

        dd = opt + 96
        for i in range(self.number_of_rva_and_sizes):
            rva, size = struct.unpack_from("<II", d, dd + i * 8)
            self.data_directories.append(DataDirectory(rva, size))

        self._parse_sections(opt)
        self._parse_exports()
        self._parse_imports()
        self._parse_delay_imports()
        self._parse_relocs()
        self._detect_tls()
        self._finalize_refusals()

    def _parse_sections(self, opt: int):
        sh = opt + self.size_of_optional_header
        for i in range(self.number_of_sections):
            base = sh + i * 40
            (name8, vsize, vaddr, rawsize, rawptr, _prel, _plin,
             _nrel, _nlin, chars) = struct.unpack_from("<8sIIIIIIHHI", self.data, base)
            name = name8.rstrip(b"\x00").decode("latin-1")
            raw = b""
            if rawsize and rawptr and rawptr + rawsize <= len(self.data):
                raw = self.data[rawptr:rawptr + rawsize]
            self.sections.append(Section(name, vsize, vaddr, rawsize, rawptr, chars, raw))

    def _parse_exports(self):
        if DIR_EXPORT >= len(self.data_directories):
            return
        de = self.data_directories[DIR_EXPORT]
        if de.rva == 0 or de.size == 0:
            return
        off = self.rva_to_off(de.rva)
        if off is None:
            return
        (_char, _tds, _maj, _min, name_rva, base, nfuncs, nnames,
         aof, aon, aono) = struct.unpack_from("<2I2H7I", self.data, off)
        self.export_dll_name = self._cstr_rva(name_rva) or None

        # name/ordinal lookup: ordinal-table[i] -> index into function table; name-table[i] -> name
        name_by_index: dict[int, str] = {}
        off_names = self.rva_to_off(aon)
        off_ords = self.rva_to_off(aono)
        if off_names is not None and off_ords is not None:
            for i in range(nnames):
                nrva = self._u32(off_names + i * 4)
                idx = self._u16(off_ords + i * 2)
                name_by_index[idx] = self._cstr_rva(nrva)

        off_funcs = self.rva_to_off(aof)
        if off_funcs is None:
            return
        for i in range(nfuncs):
            frva = self._u32(off_funcs + i * 4)
            if frva == 0:
                continue  # empty ordinal slot
            fwd = self._cstr_rva(frva) if self.in_dir(frva, DIR_EXPORT) else None
            self.exports.append(ExportEntry(
                ordinal=base + i,
                rva=frva,
                name=name_by_index.get(i),
                forwarder=fwd))

    def _parse_imports(self):
        if DIR_IMPORT >= len(self.data_directories):
            return
        di = self.data_directories[DIR_IMPORT]
        if di.rva == 0 or di.size == 0:
            return
        off = self.rva_to_off(di.rva)
        if off is None:
            return
        idx = 0
        while True:
            base = off + idx * 20
            if base + 20 > len(self.data):
                break
            oft, tds, fwd_chain, name_rva, ft = struct.unpack_from("<IIIII", self.data, base)
            if oft == 0 and name_rva == 0 and ft == 0:
                break  # null terminator
            dll_name = self._cstr_rva(name_rva)
            bound = (tds != 0 and tds != 0xFFFFFFFF)
            imp = ImportDll(dll_name, oft, ft, tds, fwd_chain, bound)
            self._parse_thunks(imp)
            self.imports.append(imp)
            idx += 1

    def _parse_thunks(self, imp: ImportDll):
        ilt_rva = imp.original_first_thunk or imp.first_thunk
        off = self.rva_to_off(ilt_rva)
        if off is None:
            return
        slot = 0
        while True:
            pos = off + slot * 4
            if pos + 4 > len(self.data):
                break
            val = self._u32(pos)
            if val == 0:
                break
            iat_slot_rva = imp.first_thunk + slot * 4
            if val & 0x80000000:
                imp.thunks.append(ImportThunk(True, val & 0x7FFFFFFF, None, None, iat_slot_rva))
            else:
                hoff = self.rva_to_off(val)
                hint = self._u16(hoff) if hoff is not None else None
                nm = self._cstr(hoff + 2) if hoff is not None else None
                imp.thunks.append(ImportThunk(False, None, hint, nm, iat_slot_rva))
            slot += 1

    def _parse_delay_imports(self):
        if DIR_DELAY_IMPORT >= len(self.data_directories):
            return
        dd = self.data_directories[DIR_DELAY_IMPORT]
        if dd.rva == 0 or dd.size == 0:
            return
        off = self.rva_to_off(dd.rva)
        if off is None:
            return
        idx = 0
        while True:
            base = off + idx * 32
            if base + 32 > len(self.data):
                break
            attrs, name_rva, _hmod, _iat, int_rva, _b, _u, _tds = struct.unpack_from("<8I", self.data, base)
            if attrs == 0 and name_rva == 0 and int_rva == 0:
                break
            # grAttrs bit0 (dlattrRva): fields are RVAs; else legacy VAs
            def to_rva(v: int) -> int:
                if v == 0:
                    return 0
                return v if (attrs & 1) else max(v - self.image_base, 0)

            name = self._cstr_rva(to_rva(name_rva))
            cnt = 0
            io = self.rva_to_off(to_rva(int_rva))
            if io is not None:
                while io + cnt * 4 + 4 <= len(self.data) and self._u32(io + cnt * 4) != 0:
                    cnt += 1
            self.delay_imports.append(DelayImportDll(name, cnt, attrs))
            idx += 1

    def _parse_relocs(self):
        if DIR_BASERELOC >= len(self.data_directories):
            return
        dr = self.data_directories[DIR_BASERELOC]
        if dr.rva == 0 or dr.size == 0:
            return
        off = self.rva_to_off(dr.rva)
        if off is None:
            return
        end = off + dr.size
        while off + 8 <= end:
            page_rva, block_size = struct.unpack_from("<II", self.data, off)
            if block_size == 0:
                break
            n = (block_size - 8) // 2
            for i in range(n):
                w = self._u16(off + 8 + i * 2)
                typ = w >> 12
                offset = w & 0x0FFF
                self.reloc_type_counts[typ] = self.reloc_type_counts.get(typ, 0) + 1
                if typ == IMAGE_REL_BASED_ABSOLUTE:
                    continue  # padding
                self.relocs.append(RelocEntry(page_rva + offset, typ))
            off += block_size

    def _detect_tls(self):
        if DIR_TLS < len(self.data_directories):
            t = self.data_directories[DIR_TLS]
            self.has_tls = (t.rva != 0 and t.size != 0)

    def _finalize_refusals(self):
        reloc_stripped = bool(self.characteristics & IMAGE_FILE_RELOCS_STRIPPED)
        has_reloc_dir = (DIR_BASERELOC < len(self.data_directories)
                         and self.data_directories[DIR_BASERELOC].rva != 0
                         and self.data_directories[DIR_BASERELOC].size != 0)
        if reloc_stripped or not has_reloc_dir:
            self.refuse_reasons.append(
                "no usable .reloc (relocations stripped) -- rebuild the DLL with /FIXED:NO")
        if any(i.bound for i in self.imports):
            names = ", ".join(i.name for i in self.imports if i.bound)
            self.refuse_reasons.append(f"bound imports present ({names}) -- not supported in v1")
        bad = [t for t in self.reloc_type_counts
               if t not in (IMAGE_REL_BASED_ABSOLUTE, IMAGE_REL_BASED_HIGHLOW)]
        if bad:
            names = ", ".join(_RELOC_TYPE_NAMES.get(t, str(t)) for t in bad)
            self.refuse_reasons.append(f"non-HIGHLOW base relocs present ({names}) -- v1 is HIGHLOW only")
        if self.has_tls:
            self.refuse_reasons.append("image has a TLS directory -- v1 refuses (can't merge two TLS dirs)")

    # ---------- convenience ----------
    @property
    def is_convertible(self) -> bool:
        return not self.refuse_reasons

    @classmethod
    def from_file(cls, path: str) -> "PE32":
        with open(path, "rb") as f:
            return cls(f.read(), path=path)
