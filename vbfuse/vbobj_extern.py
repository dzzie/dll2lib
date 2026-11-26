#!/usr/bin/env python3
r"""
vbobj_extern.py  -  turn VB6 `Declare` thunks in a compiled .OBJ into ordinary
linker externs, so the function can be resolved against a static .lib at link
time (e.g. one dll2lib produced from the C DLL). No VB source changes.

A Python port of VB6-LinkAlchemy's VBExtern.bas. VB6 emits a 25-byte thunk per
Declare:

    A1 <cache>          mov eax,[cache]
    0B C0               or  eax,eax
    74 02               je  +2
    FF E0               jmp eax
    68 <declare_struct> push offset {&"lib", &"func", ...}
    B8 <DllFunctionCall>mov eax, offset DllFunctionCall
    FF D0               call eax
    FF E0               jmp eax

with DIR32 relocs at +1 (cache), +12 (struct), +17 (callee). For each thunk
whose Lib name matches the marker, rewrite to:

    E9 <rel32>          jmp _<Func>   (REL32 reloc -> new undefined external)
    CC CC ...           (int3 padding)

reusing the +1 reloc as the new REL32 (no reloc-table growth); the +12/+17
relocs harmlessly point into the dead padding. Only an undefined external
symbol is appended.

Usage:
  vbobj_extern.py <file.OBJ> [/OUT:file] [/LIST] [/PLACEHOLDER:name]... [/PREFIX:text]
  Default marker Lib name is "<extern>"; pass /PLACEHOLDER:ucl_dll.dll to
  externalize a DLL referenced by its real name (no source edit).
"""
from __future__ import annotations
import sys
import struct

SCN_CNT_CODE = 0x20
SCN_LNK_NRELOC_OVFL = 0x01000000
REL_DIR32 = 6
REL_REL32 = 0x14
SYM_EXTERNAL = 2
THUNK_LEN = 25
OFF_CACHE, OFF_STRUCT, OFF_CALLEE = 1, 12, 17


class VbObjError(Exception):
    pass


class Decl:
    __slots__ = ("sec", "off", "lib", "func")

    def __init__(self, sec, off, lib, func):
        self.sec, self.off, self.lib, self.func = sec, off, lib, func


class CoffObj:
    def __init__(self, path: str):
        with open(path, "rb") as fh:
            data = fh.read()
        if len(data) < 20:
            raise VbObjError("file too small to be a COFF object")
        if u16(data, 0) != 0x14C:
            raise VbObjError("not an x86 (i386) COFF object")
        if u16(data, 16) != 0:
            raise VbObjError("object has an optional header; not a plain .obj")
        self.sec_count = u16(data, 2)
        self.sym_off = i32(data, 8)
        self.sym_count = i32(data, 12)
        st = self.sym_off + 18 * self.sym_count
        if self.sym_off < 20 + 40 * self.sec_count or st + 4 > len(data):
            raise VbObjError("unsupported symbol table layout")
        slen = i32(data, st)
        if slen < 4 or st + slen != len(data):
            raise VbObjError("unsupported layout: string table not at end of file")
        for si in range(self.sec_count):
            hd = 20 + 40 * si
            if i32(data, hd + 36) & SCN_LNK_NRELOC_OVFL:
                raise VbObjError("extended relocation counts not supported")
            if i32(data, hd + 28) != 0 or u16(data, hd + 34) != 0:
                raise VbObjError("COFF line numbers not supported")
        # F = everything up to the symbol table; SymBuf; StrBuf (len-prefixed)
        self.F = bytearray(data[:self.sym_off])
        self.SymBuf = bytearray(data[self.sym_off:st])
        self.StrBuf = bytearray(data[st:])

    # ---- section / symbol accessors ----
    def sec_raw(self, si):   return i32(self.F, 20 + 40 * si + 20)
    def sec_size(self, si):  return i32(self.F, 20 + 40 * si + 16)
    def sec_flags(self, si): return i32(self.F, 20 + 40 * si + 36)

    def sec_name(self, si):
        b = bytes(self.F[20 + 40 * si: 20 + 40 * si + 8])
        return b.split(b"\x00", 1)[0].decode("latin-1")

    def sym_name(self, i):
        p = i * 18
        if i32(self.SymBuf, p) == 0:
            return read_z(self.StrBuf, i32(self.SymBuf, p + 4))
        return bytes(self.SymBuf[p:p + 8]).split(b"\x00", 1)[0].decode("latin-1")

    # ---- relocations ----
    def find_reloc(self, si, site):
        hd = 20 + 40 * si
        rel_ptr = i32(self.F, hd + 24)
        n_rel = u16(self.F, hd + 32)
        for r in range(n_rel):
            q = rel_ptr + r * 10
            if i32(self.F, q) == site:
                return q
        return -1

    def is_dir32(self, si, site):
        q = self.find_reloc(si, site)
        return q >= 0 and u16(self.F, q + 8) == REL_DIR32

    def resolve(self, si, site):
        """Follow the DIR32 reloc at `site` -> (section_index, offset) or None."""
        if self.sec_raw(si) == 0 or site < 0 or site + 4 > self.sec_size(si):
            return None
        q = self.find_reloc(si, site)
        if q < 0 or u16(self.F, q + 8) != REL_DIR32:
            return None
        idx = i32(self.F, q + 4)
        if idx < 0 or idx >= self.sym_count:
            return None
        sec_num = i16(self.SymBuf, idx * 18 + 12)
        if sec_num <= 0 or sec_num > self.sec_count:
            return None
        value = i32(self.SymBuf, idx * 18 + 8)
        addend = i32(self.F, self.sec_raw(si) + site)
        return sec_num - 1, value + addend

    def read_z_at(self, si, off):
        if self.sec_raw(si) == 0 or off < 0 or off >= self.sec_size(si):
            return None
        return read_z(self.F, self.sec_raw(si) + off)

    # ---- thunk detection ----
    def is_thunk(self, p):
        f = self.F
        return (f[p] == 0xA1 and f[p + 5] == 0x0B and f[p + 6] == 0xC0
                and f[p + 7] == 0x74 and f[p + 8] == 0x02
                and f[p + 9] == 0xFF and f[p + 10] == 0xE0 and f[p + 11] == 0x68
                and f[p + 16] == 0xB8 and f[p + 21] == 0xFF and f[p + 22] == 0xD0
                and f[p + 23] == 0xFF and f[p + 24] == 0xE0)

    def find_declares(self):
        decls = []
        for si in range(self.sec_count):
            if not (self.sec_flags(si) & SCN_CNT_CODE) or self.sec_raw(si) == 0:
                continue
            raw, size = self.sec_raw(si), self.sec_size(si)
            for st in range(0, size - THUNK_LEN + 1):
                if not self.is_thunk(raw + st):
                    continue
                if not (self.is_dir32(si, st + OFF_CACHE)
                        and self.is_dir32(si, st + OFF_STRUCT)
                        and self.is_dir32(si, st + OFF_CALLEE)):
                    continue
                s = self.resolve(si, st + OFF_STRUCT)           # descriptor struct
                if not s:
                    continue
                lib_loc = self.resolve(s[0], s[1])              # struct[0] -> lib string
                func_loc = self.resolve(s[0], s[1] + 4)         # struct[4] -> func string
                if not lib_loc or not func_loc:
                    continue
                lib = self.read_z_at(lib_loc[0], lib_loc[1])
                func = self.read_z_at(func_loc[0], func_loc[1])
                if lib is not None and func is not None:
                    decls.append(Decl(si, st, lib, func))
        return decls

    # ---- symbol / patch ----
    def add_extern(self, nm: str) -> int:
        i = 0
        while i < self.sym_count:
            if self.SymBuf[i * 18 + 16] == SYM_EXTERNAL and self.sym_name(i) == nm:
                return i
            i += 1 + self.SymBuf[i * 18 + 17]
        p = self.sym_count * 18
        rec = bytearray(18)
        nb = nm.encode("latin-1")
        if len(nb) <= 8:
            rec[0:len(nb)] = nb
        else:
            off = len(self.StrBuf)
            self.StrBuf += nb + b"\x00"
            put_i32(self.StrBuf, 0, len(self.StrBuf))           # new strtab length
            put_i32(rec, 4, off)                                # name = (0, strtab off)
        rec[14] = 0x20                                          # type: function
        rec[16] = SYM_EXTERNAL                                  # storage class
        self.SymBuf += rec
        idx = self.sym_count
        self.sym_count += 1
        return idx

    def patch_one(self, d: Decl, prefix: str) -> str:
        bp = self.sec_raw(d.sec) + d.off
        nm = prefix + d.func
        idx = self.add_extern(nm)
        self.F[bp] = 0xE9                                       # jmp rel32
        for j in range(1, 5):
            self.F[bp + j] = 0
        for j in range(5, THUNK_LEN):
            self.F[bp + j] = 0xCC                               # int3 padding
        q = self.find_reloc(d.sec, d.off + OFF_CACHE)           # reuse the +1 reloc ...
        put_i32(self.F, q + 4, idx)                             # ... -> REL32 to extern
        put_u16(self.F, q + 8, REL_REL32)
        return nm

    def save(self, path: str):
        put_i32(self.F, 12, self.sym_count)                    # updated symbol count
        with open(path, "wb") as fh:
            fh.write(self.F); fh.write(self.SymBuf); fh.write(self.StrBuf)


def externalize(obj_path, markers, prefix="_", out_path=None):
    """Patch (in place, or to out_path) every Declare thunk whose Lib name is in
    `markers` into a linker extern. Returns the list of extern symbol names."""
    low = [m.lower() for m in markers]
    obj = CoffObj(obj_path)
    todo = [d for d in obj.find_declares() if d.lib.lower() in low]
    for d in todo:
        if not d.func or d.func.startswith("#"):
            raise VbObjError(f"cannot extern ordinal/empty func: {d.func!r}")
    names = [obj.patch_one(d, prefix) for d in todo]
    if todo:
        obj.save(out_path or obj_path)
    return names


# ---- little-endian byte helpers ----
def u16(b, p): return b[p] | (b[p + 1] << 8)
def i16(b, p):
    v = u16(b, p); return v - 65536 if v >= 32768 else v
def i32(b, p): return struct.unpack_from("<i", b, p)[0]
def put_i32(b, p, v): struct.pack_into("<I", b, p, v & 0xFFFFFFFF)
def put_u16(b, p, v): struct.pack_into("<H", b, p, v & 0xFFFF)
def read_z(b, p):
    e = b.find(b"\x00", p)
    if e < 0:
        e = len(b)
    return bytes(b[p:e]).decode("latin-1")


def main(argv):
    in_path = out_path = None
    prefix = "_"
    markers = []
    do_list = False
    for a in argv:
        if a.startswith("--"):          # accept --opt as an alias for /opt (shell-friendly)
            a = "/" + a[2:]
        up = a.upper()
        if up == "/LIST":
            do_list = True
        elif up.startswith("/OUT:"):
            out_path = a[5:]
        elif up.startswith("/PLACEHOLDER:"):
            markers.append(a[13:].lower())
        elif up.startswith("/PREFIX:"):
            prefix = a[8:]
        elif a.startswith("/"):
            print(f"unknown option: {a}", file=sys.stderr); return 2
        elif in_path is None:
            in_path = a
        else:
            print("multiple input files", file=sys.stderr); return 2
    if not in_path:
        print(__doc__.strip()); return 2
    if not markers:
        markers = ["<extern>"]

    obj = CoffObj(in_path)
    decls = obj.find_declares()
    if not decls:
        print("No VB6 Declare thunks found (already patched, or none).")
        return 0

    print(f"Declares found in {in_path}:")
    for d in decls:
        mark = "EXTERN" if d.lib.lower() in markers else "      "
        print(f"  [{mark}] Declare {d.func}  Lib \"{d.lib}\"  "
              f"{obj.sec_name(d.sec)}+0x{d.off:X}")
    if do_list:
        return 0

    todo = [d for d in decls if d.lib.lower() in markers]
    if not todo:
        print("Nothing to patch: no Declare uses the selected Lib name(s).")
        return 0
    for d in todo:
        if not d.func or d.func.startswith("#"):
            print(f"cannot extern ordinal/empty func: {d.func!r}", file=sys.stderr); return 1
    print()
    for d in todo:
        nm = obj.patch_one(d, prefix)
        print(f"  {d.func}  ->  undefined external symbol {nm}")
    target = out_path or in_path
    obj.save(target)
    print(f"Patched {len(todo)} declare(s) -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
