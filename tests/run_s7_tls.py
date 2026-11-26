#!/usr/bin/env python3
"""
S7 (part 3) -- TLS detect/refuse. A DLL with a TLS directory (static
__declspec(thread) data) cannot be fused in v1 (an image can hold only one TLS
directory). dll2lib must REFUSE it cleanly rather than silently mis-convert.
"""
from __future__ import annotations
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from pe32 import PE32              # noqa: E402
from convert import convert, ConvertError  # noqa: E402
from msvc import vcrun             # noqa: E402

DLL_C = r"""
__declspec(thread) int t_val = 7;
int __stdcall GetT(void) { return t_val; }
"""
DLL_DEF = "LIBRARY testtls\nEXPORTS\n    GetT\n"


def step(ok_now, label, detail=""):
    print(f"  [{'OK ' if ok_now else 'XX '}] {label}{('  ' + detail) if detail else ''}")
    return ok_now


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dll2lib_s7t_")
    print(f"build dir: {tmp}")
    ok = True
    open(os.path.join(tmp, "testtls.c"), "w").write(DLL_C)
    open(os.path.join(tmp, "testtls.def"), "w").write(DLL_DEF)
    # static TLS needs the CRT's __tls_used, so build a normal /MT DLL
    vcrun("cl /nologo /LD /MT /GS- testtls.c /link /DEF:testtls.def", tmp)
    dll = os.path.join(tmp, "testtls.dll")
    ok = step(os.path.isfile(dll), "built testtls.dll (has __declspec(thread) data)") and ok
    if not os.path.isfile(dll):
        print("\nS7(tls) FAIL"); return 1

    pe = PE32.from_file(dll)
    ok = step(pe.has_tls, "parser detects a TLS directory") and ok
    ok = step(any("TLS" in r for r in pe.refuse_reasons), "TLS is a refuse reason",
              f"{pe.refuse_reasons}") and ok

    refused = False
    try:
        convert(pe)
    except ConvertError as e:
        refused = "TLS" in str(e)
    ok = step(refused, "convert() refuses the TLS DLL with a ConvertError naming TLS") and ok

    print(f"\n{'='*50}\nS7(tls) {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
