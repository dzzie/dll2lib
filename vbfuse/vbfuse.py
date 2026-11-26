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
  3. convert each DLL to a static .lib                                 [dll2lib]
  4. relink with VB6's own LINK.EXE: captured args + patched OBJ + the .lib(s),
     forcing /OPT:NOREF (VB6's /OPT:REF dead-strips the fused obj)
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

VB98 = os.path.dirname(vbcapture.VB6_EXE)
LINK_EXE = os.path.join(VB98, "LINK.EXE")


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
    ap.add_argument("--out", help="output exe (default <exe>_fused.exe next to the vbp)")
    ap.add_argument("--work", help="work dir (default <projdir>\\vbfuse_work)")
    ap.add_argument("--run", action="store_true", help="run the fused exe when done")
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

    # 1) compile under the debugger + capture OBJs/link line
    print(f"[1/4] compiling {os.path.basename(vbp)} under debugger ...")
    cap = vbcapture.capture(vbp, work, verbose=True)
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

    # 3) convert each DLL -> static .lib. Expose each DLL's entry so a TLS
    #    callback can run its CRT/DllMain init (no bootstrap -> no __ImageBase).
    print("[3/4] converting DLL(s) -> static lib(s)")
    libs = []
    entry_syms = []
    for d in a.fuse:
        pe = PE32.from_file(d)
        if pe.refuse_reasons:
            print(f"      {os.path.basename(d)} not convertible: {pe.refuse_reasons}",
                  file=sys.stderr); return 1
        stem = os.path.splitext(os.path.basename(d))[0]
        esym = f"_{stem}_fzentry" if pe.address_of_entry_point else None
        try:
            obj_bytes = convert(pe, entry_symbol=esym)
        except ConvertError as e:
            print(f"      convert {os.path.basename(d)}: {e}", file=sys.stderr); return 1
        with open(os.path.join(work, stem + ".obj"), "wb") as f:
            f.write(obj_bytes)
        r = vcrun(f'lib /nologo /out:"{stem}.lib" "{stem}.obj"', work)
        if r.returncode != 0 or not os.path.isfile(os.path.join(work, stem + ".lib")):
            print(f"      lib.exe failed for {stem}:\n{r.stdout}{r.stderr}", file=sys.stderr)
            return 1
        libs.append(stem + ".lib")
        if esym:
            entry_syms.append(esym)
        print(f"      {os.path.basename(d)} -> {stem}.lib"
              f"{'  (+entry ' + esym + ')' if esym else ''}")

    # emit a TLS-callback object that runs each fused DLL's entry at load time
    tls_obj = None
    if entry_syms:
        tls_obj = os.path.join(work, "fzinit.obj")
        emit_tls_init(entry_syms, tls_obj)
        print(f"      TLS init object -> fzinit.obj (runs: {', '.join(entry_syms)})")

    # 4) relink with VB6's own LINK.EXE
    print("[4/4] relinking fused exe")
    toks = tokenize(cap.link_cmd)[1:]        # drop the leading "LINK"
    orig_out = next((t.split(":", 1)[1] for t in toks if t.upper().startswith("/OUT:")), "out.exe")
    stem = os.path.splitext(os.path.basename(orig_out))[0]
    fused = os.path.abspath(a.out) if a.out else os.path.join(proj_dir, stem + "_fused.exe")

    obj_map = {os.path.basename(p).lower(): p for p in cap.objs}
    args = [LINK_EXE]
    saw_noref = False
    for t in toks:
        tl, tu = t.lower(), t.upper()
        if tl.endswith(".obj"):
            args.append(obj_map.get(os.path.basename(t).lower(), t))
        elif tu.startswith("/OUT:"):
            args.append("/OUT:" + fused)
        elif tu == "/OPT:REF" or tu == "/OPT:NOREF":
            args.append("/OPT:NOREF"); saw_noref = True
        else:
            args.append(t)
    if not saw_noref:
        args.append("/OPT:NOREF")
    if tls_obj:
        args.append(tls_obj)
        args.append("/INCLUDE:__tls_used")       # force the linker to wire the TLS dir
    args += [os.path.join(work, lib) for lib in libs]

    env = dict(os.environ); env["PATH"] = VB98 + ";" + env["PATH"]
    r = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(fused):
        print(f"LINK failed:\n{r.stdout}{r.stderr}", file=sys.stderr); return 1
    print(f"\nFUSED -> {fused}  ({os.path.getsize(fused)} bytes)")
    print(f"       no runtime dependency on: {', '.join(markers)}")

    if a.run:
        print(f"\nrunning: {os.path.basename(fused)} {' '.join(runargs)}")
        rr = subprocess.run([fused] + runargs)
        print(f"exit code: {rr.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
