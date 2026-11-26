#!/usr/bin/env python3
"""
dll2lib  -  generic PE32 (i386) DLL -> full static COFF .lib converter.

    dll2lib foo.dll [/OUT:foo.lib] [/DEF:foo.def] [/DUMP]

STAGE S0 (current): parsing + validation + dump only. Conversion stages
(S1+) are not wired up yet; running a convert prints the parsed facts and
the REFUSE verdict so we can validate the reader against dumpbin.
"""

from __future__ import annotations
import sys
import os

from pe32 import PE32, PEError, _RELOC_TYPE_NAMES
from convert import convert, ConvertError

CHAR_BITS = [
    (0x0020, "CODE"), (0x0040, "INITDATA"), (0x0080, "BSS"),
    (0x02000000, "DISCARDABLE"), (0x10000000, "SHARED"),
    (0x20000000, "EXEC"), (0x40000000, "READ"), (0x80000000, "WRITE"),
]


def _chars(flags: int) -> str:
    return "|".join(n for b, n in CHAR_BITS if flags & b) or "-"


def dump(pe: PE32) -> None:
    p = print
    p(f"== {pe.path or '<bytes>'} ==")
    p(f"  machine         : 0x{pe.machine:04X} "
      f"({'i386' if pe.machine == 0x14C else 'OTHER'})")
    p(f"  optional magic  : 0x{pe.opt_magic:04X} "
      f"({'PE32' if pe.opt_magic == 0x10B else 'PE32+/other'})")
    p(f"  characteristics : 0x{pe.characteristics:04X} "
      f"({'DLL ' if pe.characteristics & 0x2000 else ''}"
      f"{'RELOCS_STRIPPED' if pe.characteristics & 1 else ''})".rstrip())
    p(f"  image base      : 0x{pe.image_base:08X}")
    p(f"  entry point RVA : 0x{pe.address_of_entry_point:08X}")
    p(f"  size of image   : 0x{pe.size_of_image:08X}")
    p(f"  section align   : 0x{pe.section_alignment:X}   file align: 0x{pe.file_alignment:X}")
    p(f"  data dirs       : {pe.number_of_rva_and_sizes}")

    p(f"\n  sections ({len(pe.sections)}):")
    p(f"    {'name':<9}{'VA':>12}{'VSize':>10}{'RawSize':>10}{'RawPtr':>10}  flags")
    for s in pe.sections:
        p(f"    {s.name:<9}{s.virtual_address:>#12x}{s.virtual_size:>#10x}"
          f"{s.size_of_raw_data:>#10x}{s.pointer_to_raw_data:>#10x}  {_chars(s.characteristics)}")

    if pe.export_dll_name or pe.exports:
        named = [e for e in pe.exports if e.name]
        fwd = [e for e in pe.exports if e.forwarder]
        p(f"\n  exports (dll name '{pe.export_dll_name}'): "
          f"{len(pe.exports)} total, {len(named)} named, {len(fwd)} forwarders")
        for e in pe.exports[:12]:
            tag = f" -> {e.forwarder}" if e.forwarder else ""
            p(f"    @{e.ordinal:<6} rva=0x{e.rva:08X}  {e.name or '(by-ordinal)'}{tag}")
        if len(pe.exports) > 12:
            p(f"    ... (+{len(pe.exports) - 12} more)")

    if pe.imports:
        p(f"\n  imports ({len(pe.imports)} DLLs):")
        for imp in pe.imports:
            p(f"    {imp.name:<20} {len(imp.thunks)} syms"
              f"{'  [BOUND]' if imp.bound else ''}")

    if pe.delay_imports:
        p(f"\n  delay imports ({len(pe.delay_imports)} DLLs):")
        for d in pe.delay_imports:
            p(f"    {d.name:<20} {d.count} syms  [delay-load]")

    if pe.reloc_type_counts:
        parts = ", ".join(f"{_RELOC_TYPE_NAMES.get(t, str(t))}={c}"
                          for t, c in sorted(pe.reloc_type_counts.items()))
        p(f"\n  base relocs     : {len(pe.relocs)} fixups ({parts})")
    else:
        p(f"\n  base relocs     : none")

    if pe.has_tls:
        p("  TLS directory   : PRESENT")

    p("")
    if pe.is_convertible:
        p("  VERDICT: convertible (i386 PE32, .reloc present, no blockers)")
    else:
        p("  VERDICT: REFUSE --")
        for r in pe.refuse_reasons:
            p(f"    - {r}")


def main(argv: list[str]) -> int:
    pos = []
    opt_out = None
    opt_def = None
    want_dump = False
    for a in argv:
        u = a.upper()
        if u in ("/DUMP", "--DUMP", "-DUMP"):
            want_dump = True
        elif u.startswith("/OUT:") or u.startswith("--OUT:"):
            opt_out = a.split(":", 1)[1]
        elif u.startswith("/DEF:") or u.startswith("--DEF:"):
            opt_def = a.split(":", 1)[1]
        elif a.startswith("-") or a.startswith("/"):
            print(f"unknown option: {a}", file=sys.stderr)
            return 2
        else:
            pos.append(a)

    if len(pos) != 1:
        print(__doc__.strip())
        return 2

    path = pos[0]
    if not os.path.isfile(path):
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    try:
        pe = PE32.from_file(path)
    except PEError as e:
        print(f"PE parse error: {e}", file=sys.stderr)
        return 3

    if want_dump:
        dump(pe)
        return 0 if pe.is_convertible else 1

    if not pe.is_convertible:
        print(f"REFUSE: {path} cannot be converted --")
        for r in pe.refuse_reasons:
            print(f"  - {r}")
        return 1

    return do_convert(pe, path, opt_out, opt_def)


def parse_def_stdcall(def_path: str) -> dict[str, int]:
    """Derive {export_name: stdcall_arg_bytes} from a .def's EXPORTS alias lines
    of the form `_Name@n=_Name` (or `__imp__Name@n=...`). This is how the user
    supplies stdcall decoration that the export table itself has stripped."""
    import re
    args: dict[str, int] = {}
    in_exports = False
    pat = re.compile(r"^_(?:_imp_)?_?([A-Za-z0-9_]+)@(\d+)\b")
    with open(def_path, "r") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            kw = line.upper()
            if kw == "EXPORTS":
                in_exports = True
                continue
            if kw.split(" ", 1)[0] in ("LIBRARY", "NAME", "SECTIONS", "STUBSIZE",
                                       "VERSION", "HEAPSIZE", "STACKSIZE"):
                in_exports = False
                continue
            if in_exports and "=" in line:
                m = pat.match(line.split("=", 1)[0].strip())
                if m:
                    args[m.group(1)] = int(m.group(2))
    return args


def do_convert(pe: PE32, path: str, out_lib: str | None, def_path: str | None) -> int:
    from msvc import vcrun, find_vcvars32

    stem = os.path.splitext(os.path.basename(path))[0]
    out_lib = out_lib or (stem + ".lib")
    out_dir = os.path.dirname(os.path.abspath(out_lib)) or "."
    obj_name = os.path.splitext(os.path.basename(out_lib))[0] + ".obj"
    obj_path = os.path.join(out_dir, obj_name)

    stdcall_args = parse_def_stdcall(def_path) if def_path else None
    init_symbol = "_" + stem + "_StaticInit"
    try:
        obj = convert(pe, stdcall_args=stdcall_args, init_symbol=init_symbol)
    except ConvertError as e:
        print(f"convert error: {e}", file=sys.stderr)
        return 1
    with open(obj_path, "wb") as f:
        f.write(obj)
    nexp = len([e for e in pe.exports if e.forwarder is None and e.rva != 0])
    print(f"converted {path}: {len(pe.sections)} sections, {len(pe.relocs)} relocs, "
          f"{nexp} exports -> {obj_path} ({len(obj)} bytes)")
    if pe.address_of_entry_point:
        print(f"  bootstrap: call `{stem}_StaticInit()` ONCE before using any export "
              f"(runs the DLL's DllMain/CRT init).")

    try:
        find_vcvars32()
    except RuntimeError:
        print(f"wrote {obj_path}. MS x86 tools not found; wrap it yourself:\n"
              f"  lib /out:{out_lib} {obj_name}")
        return 0
    r = vcrun(f'lib /nologo /out:"{os.path.basename(out_lib)}" "{obj_name}"', out_dir)
    if r.returncode != 0 or not os.path.isfile(out_lib):
        print(f"lib.exe failed:\n{r.stdout}{r.stderr}", file=sys.stderr)
        return 1
    print(f"wrote {out_lib}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
