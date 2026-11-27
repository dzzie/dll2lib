#!/usr/bin/env python3
r"""
vbfuse  -  fuse C DLL(s) into a compiled VB6 program (one command).

    vbfuse <project.vbp> --fuse foo.dll [--fuse bar.dll ...]
           [--out fused.exe] [--work <dir>] [--run [-- <args>]]

Pipeline (on-demand, nothing installed or permanently changed):
  1. run VB6.EXE /make under a debugger; capture the OBJs + link line at the
     LINK.EXE spawn (VB6 deletes the OBJs afterward)                [vbcapture]
  2. rewrite the project OBJ's `Declare Lib "foo.dll"` thunks into linker
     externs, using the DLL's own name as the marker (no VB source edit)
                                                                    [vbobj_extern]
  3. convert each DLL to a COFF object                                 [dll2lib]
  4. relink with VB6's own LINK.EXE: captured args + patched OBJ + the fused
     object(s), forcing /OPT:NOREF (VB6's /OPT:REF dead-strips the fused obj)
     (--lib also archives the object(s) into static .lib deliverables)
"""
from __future__ import annotations
import os
import sys
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # the dll2lib package dir
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import vbcapture                                   # noqa: E402
from vbobj_extern import externalize, VbObjError   # noqa: E402
from tlsinit import emit_tls_init                  # noqa: E402
from pe32 import PE32                              # noqa: E402
from convert import convert, ConvertError          # noqa: E402
from msvc import vcrun                             # noqa: E402
import fzmeta                                      # noqa: E402

VBFUSE_VERSION = "1.0"
VB98 = os.path.dirname(vbcapture.VB6_EXE)
LINK_EXE = os.path.join(VB98, "LINK.EXE")


def find_vbstatic():
    import glob
    bundled = os.path.join(ROOT, "tools", "VBStatic.exe")   # the canonical copy
    if os.path.isfile(bundled):
        return bundled
    here_up = os.path.dirname(ROOT)                          # .../fuser
    for pat in (os.path.join(here_up, "VB6-LinkAlchemy*", "vbstatic", "VBStatic.exe"),
                os.path.join(os.path.expanduser("~"), "Desktop", "**", "VBStatic.exe")):
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]
    return None


def tokenize(s: str):
    toks, cur, inq, started = [], "", False, False
    for ch in s:
        if ch == '"':
            inq = not inq; started = True
        elif ch in " \t" and not inq:
            if started:
                toks.append(cur); cur = ""; started = False
        else:
            cur += ch; started = True
    if started:
        toks.append(cur)
    return toks


def main(argv):
    # split off anything after a lone "--" as args for --run
    runargs = []
    if "--" in argv:
        i = argv.index("--"); runargs = argv[i + 1:]; argv = argv[:i]
    ap = argparse.ArgumentParser(prog="vbfuse", add_help=True)
    ap.add_argument("vbp")
    ap.add_argument("--fuse", action="append", default=[], metavar="DLL",
                    help="C DLL to fuse in (repeatable)")
    ap.add_argument("--fuse-runtime", metavar="MSVBVM60",
                    help="also fuse the VB6 runtime (msvbvm60.dll) via VBStatic "
                         "-> a fully standalone exe")
    ap.add_argument("--vbstatic", help="path to VBStatic.exe (for --fuse-runtime)")
    ap.add_argument("--out", help="output exe (default <exe>_fused.exe next to the vbp)")
    ap.add_argument("--work", help="work dir (default <projdir>\\vbfuse_work)")
    ap.add_argument("--run", action="store_true", help="run the fused exe when done")
    ap.add_argument("--pcode", action="store_true",
                    help="compile the VB6 project as P-code (CompilationType=-1) for "
                         "the capture, instead of native; the .vbp is restored after. "
                         "Fusion still works (Declare thunks stay native).")
    ap.add_argument("--lib", action="store_true",
                    help="also emit the dll2lib static .lib(s) for the fused DLL(s) "
                         "as a reusable deliverable (needs lib.exe / MS build tools; "
                         "not required for the fuse itself)")
    ap.add_argument("--console", action="store_true",
                    help="build the fused exe with the CONSOLE subsystem (so a VB "
                         "ConsolePrint-style Sub can write to stdout -- handy for testing)")
    a = ap.parse_args(argv)

    vbp = os.path.abspath(a.vbp)
    if not os.path.isfile(vbp):
        print(f"no such project: {vbp}", file=sys.stderr); return 2
    if not a.fuse:
        print("nothing to fuse; pass --fuse <dll>", file=sys.stderr); return 2
    for d in a.fuse:
        if not os.path.isfile(d):
            print(f"no such dll: {d}", file=sys.stderr); return 2
    proj_dir = os.path.dirname(vbp)
    work = os.path.abspath(a.work) if a.work else os.path.join(proj_dir, "vbfuse_work")
    markers = [os.path.basename(d) for d in a.fuse]

    # 1) compile under the debugger + capture OBJs/link line.
    #    --pcode temporarily flips the .vbp to P-code (CompilationType=-1) for the
    #    compile, then restores it. (Declare thunks stay native in the main OBJ, so
    #    fusion still works; only the VB logic becomes P-code.)
    orig_vbp = None
    if a.pcode:
        import re
        orig_vbp = open(vbp, "r", encoding="latin-1", newline="").read()
        if "CompilationType=" in orig_vbp:
            txt = re.sub(r"CompilationType=-?\d+", "CompilationType=-1", orig_vbp, count=1)
        else:
            txt = orig_vbp.rstrip("\r\n") + "\r\nCompilationType=-1\r\n"
        open(vbp, "w", encoding="latin-1", newline="").write(txt)
        print(f"[1/4] compiling {os.path.basename(vbp)} under debugger (P-code) ...")
    else:
        print(f"[1/4] compiling {os.path.basename(vbp)} under debugger ...")
    try:
        cap = vbcapture.capture(vbp, work, verbose=True)
    finally:
        if orig_vbp is not None:
            open(vbp, "w", encoding="latin-1", newline="").write(orig_vbp)
    if not cap.ok:
        print("VB6 build did not produce capturable OBJs / link line.")
        print(cap.log or "(no build log)"); return 1
    print(f"      captured {len(cap.objs)} OBJs; build log: {cap.log.splitlines()[0]}")

    # 2) externalize the Declare thunks for the fused DLL(s)
    print(f"[2/4] externalizing Declares for: {', '.join(markers)}")
    patched = []
    for obj in cap.objs:
        try:
            names = externalize(obj, markers)
        except VbObjError as e:
            print(f"      {os.path.basename(obj)}: {e}", file=sys.stderr); return 1
        if names:
            print(f"      {os.path.basename(obj)}: {', '.join(names)}")
            patched += names
    if not patched:
        print(f"      WARNING: no Declare matched {markers} -- nothing to fuse.")
        return 1

    # identify the exe + main project OBJ from the captured link line
    link_toks = tokenize(cap.link_cmd)[1:]
    orig_out = next((t.split(":", 1)[1] for t in link_toks if t.upper().startswith("/OUT:")), "out.exe")
    exe_stem = os.path.splitext(os.path.basename(orig_out))[0]
    fused = os.path.abspath(a.out) if a.out else os.path.join(proj_dir, exe_stem + "_fused.exe")
    main_obj = next((o for o in cap.objs
                     if os.path.splitext(os.path.basename(o))[0].lower() == exe_stem.lower()), None)

    # 3) convert each DLL -> a COFF object (hand-rolled, no tools). Expose each
    #    DLL's entry so a TLS callback can run its CRT/DllMain init (no bootstrap
    #    -> no __ImageBase). We link the .obj directly; `--lib` also archives it
    #    into a static .lib (the dll2lib product -- needs lib.exe / build tools).
    print("[3/4] converting DLL(s) -> fused object(s)")
    libs = []
    fused_objs = []
    entry_syms = []
    export_names = []
    for d in a.fuse:
        pe = PE32.from_file(d)
        if pe.refuse_reasons:
            print(f"      {os.path.basename(d)} not convertible: {pe.refuse_reasons}",
                  file=sys.stderr); return 1
        export_names += [e.name for e in pe.exports
                         if e.name and e.forwarder is None and e.rva != 0]
        stem = os.path.splitext(os.path.basename(d))[0]
        esym = f"_{stem}_fzentry" if pe.address_of_entry_point else None
        try:
            obj_bytes = convert(pe, entry_symbol=esym)
        except ConvertError as e:
            print(f"      convert {os.path.basename(d)}: {e}", file=sys.stderr); return 1
        with open(os.path.join(work, stem + ".obj"), "wb") as f:
            f.write(obj_bytes)
        fused_objs.append(stem + ".obj")
        if a.lib:                                   # opt-in: also emit the static .lib
            r = vcrun(f'lib /nologo /out:"{stem}.lib" "{stem}.obj"', work)
            if r.returncode != 0 or not os.path.isfile(os.path.join(work, stem + ".lib")):
                print(f"      lib.exe failed for {stem}:\n{r.stdout}{r.stderr}", file=sys.stderr)
                return 1
            libs.append(stem + ".lib")
        if esym:
            entry_syms.append(esym)
        print(f"      {os.path.basename(d)} -> {stem}.obj"
              f"{' + ' + stem + '.lib' if a.lib else ''}"
              f"{'  (+entry ' + esym + ')' if esym else ''}")

    # emit a TLS-callback object that runs each fused DLL's entry at load time
    tls_obj = None
    if entry_syms:
        tls_obj = os.path.join(work, "fzinit.obj")
        emit_tls_init(entry_syms, tls_obj)
        print(f"      TLS init object -> fzinit.obj (runs: {', '.join(entry_syms)})")

    # 3b) optionally fuse the VB6 runtime (msvbvm60) via VBStatic
    runtime_fused = False
    if a.fuse_runtime:
        vbs = a.vbstatic or find_vbstatic()
        if not vbs or not os.path.isfile(vbs):
            print("--fuse-runtime: VBStatic.exe not found; pass --vbstatic <path>",
                  file=sys.stderr); return 1
        if not main_obj:
            print("could not identify the main project OBJ for VBStatic", file=sys.stderr); return 1
        print(f"[3b] fusing VB runtime {os.path.basename(a.fuse_runtime)} via VBStatic")
        r = subprocess.run([vbs, os.path.abspath(a.fuse_runtime), main_obj],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"VBStatic failed:\n{r.stdout}{r.stderr}", file=sys.stderr); return 1
        runtime_fused = True
        print(f"      fused msvbvm60 into {os.path.basename(main_obj)} "
              f"({os.path.getsize(main_obj)} bytes)")

    # 4) relink
    print("[4/4] relinking fused exe")
    subsys = "/SUBSYSTEM:CONSOLE" if a.console else "/SUBSYSTEM:WINDOWS,4.0"
    if runtime_fused:
        # VBStatic put the runtime (and the symbols the other OBJs need) into the
        # main OBJ -> use its entry/flags, link all captured OBJs, no VBAEXE6.LIB.
        ordered = sorted(cap.objs, key=lambda o: 0 if o == main_obj else 1)
        args = [LINK_EXE, "/NOLOGO", subsys, "/NODEFAULTLIB",
                "/ENTRY:_VBStaticEntry", "/BASE:0x400000", "/INCREMENTAL:NO",
                "/OPT:NOREF", "/IGNORE:4078", "/OUT:" + fused] + ordered
    else:
        obj_map = {os.path.basename(p).lower(): p for p in cap.objs}
        args = [LINK_EXE]
        saw_noref = False
        for t in link_toks:
            tl, tu = t.lower(), t.upper()
            if tl.endswith(".obj"):
                args.append(obj_map.get(os.path.basename(t).lower(), t))
            elif tu.startswith("/OUT:"):
                args.append("/OUT:" + fused)
            elif tu.startswith("/SUBSYSTEM:"):
                args.append(subsys if a.console else t)
            elif tu == "/OPT:REF" or tu == "/OPT:NOREF":
                args.append("/OPT:NOREF"); saw_noref = True
            else:
                args.append(t)
        if not saw_noref:
            args.append("/OPT:NOREF")
    if tls_obj:
        args.append(tls_obj)
        args.append("/INCLUDE:__tls_used")       # force the linker to wire the TLS dir
    # Always link the fused .obj DIRECTLY (fully included) rather than a .lib --
    # LINK's export pre-pass can't resolve exported symbols from a static lib
    # (LNK2001 'build of exports file'), and unused exports would never be pulled
    # in. (The optional --lib .lib is a separate, reusable deliverable.)
    args += [os.path.join(work, o) for o in fused_objs]

    # re-emit every fused export in the exe's own export table (name -> fused RVA)
    if export_names:
        seen, lines = set(), ["EXPORTS"]
        for nm in export_names:
            if nm not in seen:
                seen.add(nm)
                lines.append(f"    {nm}")            # LINK maps `Name` -> dll2lib's `_Name`
        def_path = os.path.join(work, "fzexports.def")
        with open(def_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        args.append("/DEF:" + def_path)
        print(f"      exporting {len(seen)} fused symbol(s) into the exe (analysis aid)")

    # build-info record: aes("vbFuse<ver> | <user>@<host> | <when> | <exepath>")
    import getpass
    import platform
    from datetime import datetime
    _user = os.environ.get("USERNAME") or getpass.getuser() or "?"
    _host = os.environ.get("COMPUTERNAME") or platform.node() or "?"
    _when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _blob = fzmeta.make_blob(VBFUSE_VERSION, _user, _host, _when, fused)
    _mark_obj = os.path.join(work, "fzmark.obj")
    fzmeta.emit_obj(_blob, _mark_obj)
    args.append(_mark_obj)
    args.append("/INCLUDE:" + fzmeta.SYMBOL)
    print(f"      build stamp embedded (AES-128, {len(_blob)} bytes)")

    env = dict(os.environ); env["PATH"] = VB98 + ";" + env["PATH"]
    r = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(fused):
        print(f"LINK failed:\n{r.stdout}{r.stderr}", file=sys.stderr); return 1
    if export_names:                              # drop LINK's exe-side .exp/.lib
        stem = os.path.splitext(fused)[0]
        for ext in (".exp", ".lib"):
            try:
                os.remove(stem + ext)
            except OSError:
                pass
    print(f"\nFUSED -> {fused}  ({os.path.getsize(fused)} bytes)")
    print(f"       no runtime dependency on: {', '.join(markers)}")
    if a.lib and libs:
        print(f"       static lib(s): {', '.join(os.path.join(work, l) for l in libs)}")

    if a.run:
        print(f"\nrunning: {os.path.basename(fused)} {' '.join(runargs)}")
        rr = subprocess.run([fused] + runargs)
        print(f"exit code: {rr.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
