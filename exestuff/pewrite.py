#!/usr/bin/env python3
r"""
pewrite.py  -  minimal PE32 surgery for exestuff: append sections to a finished
exe and patch the headers.  32-bit (PE32/i386) only.

This is the "writer" half; pe32.py is the reader.  We parse only the header
fields we need to modify, by offset, so the rest of the file is passed through
byte-for-byte.
"""
from __future__ import annotations
import struct

# section Characteristics
SCN_CNT_CODE = 0x00000020
SCN_CNT_INITIALIZED_DATA = 0x00000040
SCN_MEM_EXECUTE = 0x20000000
SCN_MEM_READ = 0x40000000
SCN_MEM_WRITE = 0x80000000
CHARS_TEXT = SCN_CNT_CODE | SCN_MEM_EXECUTE | SCN_MEM_READ
CHARS_RDATA = SCN_CNT_INITIALIZED_DATA | SCN_MEM_READ
CHARS_DATA = SCN_CNT_INITIALIZED_DATA | SCN_MEM_READ | SCN_MEM_WRITE


def _align(v: int, a: int) -> int:
    return (v + a - 1) & ~(a - 1)


class PEImage:
    """Mutable in-memory PE32; append sections, then .to_bytes()."""

    def __init__(self, data: bytes):
        self.b = bytearray(data)
        if self.b[:2] != b"MZ":
            raise ValueError("not MZ")
        self.e_lfanew = struct.unpack_from("<I", self.b, 0x3C)[0]
        if self.b[self.e_lfanew:self.e_lfanew + 4] != b"PE\0\0":
            raise ValueError("no PE signature")
        self.coff = self.e_lfanew + 4                 # IMAGE_FILE_HEADER
        self.opt = self.coff + 20                      # IMAGE_OPTIONAL_HEADER
        magic = struct.unpack_from("<H", self.b, self.opt)[0]
        if magic != 0x10B:
            raise ValueError("not PE32 (0x10B); 32-bit only")
        self.size_opt = struct.unpack_from("<H", self.b, self.coff + 16)[0]
        self.sectbl = self.opt + self.size_opt         # section table
        self.nsect = struct.unpack_from("<H", self.b, self.coff + 2)[0]
        self.sect_align = struct.unpack_from("<I", self.b, self.opt + 32)[0]
        self.file_align = struct.unpack_from("<I", self.b, self.opt + 36)[0]
        self.size_headers = struct.unpack_from("<I", self.b, self.opt + 60)[0]

    # ---- optional-header fields ----
    @property
    def image_base(self) -> int:
        return struct.unpack_from("<I", self.b, self.opt + 28)[0]

    def _set_u32(self, off, v):
        struct.pack_into("<I", self.b, off, v)

    def _set_u16(self, off, v):
        struct.pack_into("<H", self.b, off, v)

    def sections(self):
        out = []
        for i in range(self.nsect):
            o = self.sectbl + i * 40
            name = self.b[o:o + 8].rstrip(b"\0").decode("latin-1")
            vs, va, rs, rp = struct.unpack_from("<IIII", self.b, o + 8)
            out.append((name, vs, va, rs, rp, o))
        return out

    def next_rva(self) -> int:
        hi = 0
        for _, vs, va, rs, _, _ in self.sections():
            hi = max(hi, va + max(vs, rs))
        return _align(hi, self.sect_align)

    def add_section(self, name: str, data: bytes, chars: int,
                    vsize: int | None = None) -> int:
        """Append a section; returns its RVA.  vsize defaults to len(data)
        (pass a larger vsize for a bss-style tail)."""
        hdr_off = self.sectbl + self.nsect * 40
        if hdr_off + 40 > self.size_headers:
            raise ValueError("no room in header for another section entry")
        va = self.next_rva()
        rp = _align(len(self.b), self.file_align)
        rs = _align(len(data), self.file_align)
        vs = vsize if vsize is not None else len(data)

        nm = name.encode("latin-1")[:8].ljust(8, b"\0")
        hdr = nm + struct.pack("<IIII", vs, va, rs, rp) + struct.pack("<IIHH", 0, 0, 0, 0) + struct.pack("<I", chars)
        self.b[hdr_off:hdr_off + 40] = hdr

        self.nsect += 1
        self._set_u16(self.coff + 2, self.nsect)
        self._set_u32(self.opt + 56, _align(va + vs, self.sect_align))  # SizeOfImage

        # pad file to rp, then the section bytes padded to rs
        if len(self.b) < rp:
            self.b += b"\0" * (rp - len(self.b))
        self.b += data + b"\0" * (rs - len(data))
        return va

    # ---- RVA helpers / data directories / patching ----
    def rva_to_off(self, rva: int) -> int | None:
        for _, vs, va, rs, rp, _ in self.sections():
            if va <= rva < va + max(vs, rs):
                return rp + (rva - va)
        return None

    def read_rva(self, rva: int, n: int) -> bytes:
        o = self.rva_to_off(rva)
        return bytes(self.b[o:o + n]) if o is not None else b""

    def patch_rva(self, rva: int, data: bytes):
        o = self.rva_to_off(rva)
        if o is None:
            raise ValueError("rva 0x%X not mapped" % rva)
        self.b[o:o + len(data)] = data

    def set_subsystem(self, n: int):
        struct.pack_into("<H", self.b, self.opt + 68, n)   # 2=GUI, 3=console

    def get_datadir(self, i: int):
        o = self.opt + 96 + i * 8
        return struct.unpack_from("<II", self.b, o)          # (rva, size)

    def set_datadir(self, i: int, rva: int, size: int):
        struct.pack_into("<II", self.b, self.opt + 96 + i * 8, rva, size)

    def to_bytes(self) -> bytes:
        return bytes(self.b)


def append_section(in_path: str, out_path: str, name: str, data: bytes, chars: int):
    pe = PEImage(open(in_path, "rb").read())
    rva = pe.add_section(name, data, chars)
    open(out_path, "wb").write(pe.to_bytes())
    return rva
