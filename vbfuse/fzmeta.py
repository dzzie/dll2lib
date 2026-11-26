#!/usr/bin/env python3
r"""
fzmeta.py  -  embed a small build-info record in a fused exe.

Writes a short AES-128 record (tool version, builder, time, output path) as a
COFF `.vbfuse` chunk, linked in like fzinit/tlsinit and pinned with /INCLUDE.
No runtime effect.

AES-128 is hand-rolled here, in keeping with the rest of the project (the PE
reader and COFF writer are hand-rolled too). The 16-byte key is in this source.

CLI:  python fzmeta.py <fused.exe>      # print the record
"""
from __future__ import annotations
import os
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # dll2lib dir
from coff import CoffBuilder, FLAGS_RDATA

KEY = b"i am not a crook"          # 16 bytes == AES-128
SECTION = ".vbfuse"                # record section
SYMBOL = "__fz_meta"
# MARKER (defined below, once AES exists) = aes("nixon sayz"): a fixed 16-byte
# prefix that marks the start of the record.

# ---------------------------------------------------------------- AES-128 ----
_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _mul(a: int, b: int) -> int:
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return r


def _expand_key(key: bytes):
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]                       # RotWord
            t = [_SBOX[b] for b in t]               # SubWord
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _add_round_key(s, w, rnd):
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[rnd * 4 + c][r]


def _encrypt_block(block: bytes, w) -> bytes:
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    _add_round_key(s, w, 0)
    for rnd in range(1, 10):
        for r in range(4):
            for c in range(4):
                s[r][c] = _SBOX[s[r][c]]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3)
            s[3][c] = _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)
        _add_round_key(s, w, rnd)
    for r in range(4):
        for c in range(4):
            s[r][c] = _SBOX[s[r][c]]
    for r in range(1, 4):
        s[r] = s[r][r:] + s[r][:r]
    _add_round_key(s, w, 10)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _decrypt_block(block: bytes, w) -> bytes:
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    _add_round_key(s, w, 10)
    for rnd in range(9, 0, -1):
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]            # InvShiftRows
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV_SBOX[s[r][c]]
        _add_round_key(s, w, rnd)
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
            s[1][c] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
            s[2][c] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
            s[3][c] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
    for r in range(1, 4):
        s[r] = s[r][-r:] + s[r][:-r]
    for r in range(4):
        for c in range(4):
            s[r][c] = _INV_SBOX[s[r][c]]
    _add_round_key(s, w, 0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes128_ecb_encrypt(pt: bytes, key: bytes = KEY) -> bytes:
    w = _expand_key(key)
    pad = 16 - (len(pt) % 16)                       # PKCS#7
    pt = pt + bytes([pad]) * pad
    return b"".join(_encrypt_block(pt[i:i + 16], w) for i in range(0, len(pt), 16))


def aes128_ecb_decrypt(ct: bytes, key: bytes = KEY) -> bytes:
    w = _expand_key(key)
    out = b"".join(_decrypt_block(ct[i:i + 16], w) for i in range(0, len(ct), 16))
    pad = out[-1] if out else 0
    if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
        out = out[:-pad]
    return out


# aes("nixon sayz") -- fixed 16-byte record marker
MARKER = aes128_ecb_encrypt(b"nixon sayz")
_HDR = len(MARKER) + 3             # marker(16) + ver(1) + len(2)


# ---------------------------------------------------------------- record ----
def make_blob(version: str, user: str, host: str, when: str, exepath: str) -> bytes:
    """Build the on-disk record: MARKER + ver + len + AES ciphertext."""
    plain = f"vbFuse{version} | {user}@{host} | {when} | {exepath}".encode("utf-8", "replace")
    ct = aes128_ecb_encrypt(plain)
    return MARKER + bytes([1]) + struct.pack("<H", len(ct)) + ct


def decode_blob(blob: bytes) -> str | None:
    """Decode a blob produced by make_blob; None if it isn't one."""
    if len(blob) < _HDR or blob[:len(MARKER)] != MARKER:
        return None
    n = struct.unpack_from("<H", blob, len(MARKER) + 1)[0]
    ct = blob[_HDR:_HDR + n]
    if len(ct) != n or n % 16:
        return None
    try:
        return aes128_ecb_decrypt(ct).decode("utf-8")
    except Exception:
        return None


def emit_obj(blob: bytes, out_path: str) -> None:
    """Write a COFF object carrying the record in a `.vbfuse` chunk."""
    cb = CoffBuilder()
    sec = cb.add_section(SECTION, FLAGS_RDATA)
    sec.append(blob)
    cb.define(SYMBOL, 0, sec.number)                # external -> /INCLUDE pins it
    with open(out_path, "wb") as f:
        f.write(cb.build())


def read_from_file(path: str) -> str | None:
    """Scan a built exe for the record and decode it."""
    with open(path, "rb") as f:
        data = f.read()
    i = data.find(MARKER)
    while i != -1:
        got = decode_blob(data[i:i + _HDR + 0xFFFF])
        if got and got.startswith("vbFuse"):
            return got
        i = data.find(MARKER, i + 1)
    return None


if __name__ == "__main__":
    # self-test against the FIPS-197 AES-128 test vector, then run the CLI
    _k = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    _p = bytes.fromhex("00112233445566778899aabbccddeeff")
    _c = _encrypt_block(_p, _expand_key(_k)).hex()
    assert _c == "69c4e0d86a7b0430d8cdb78070b4c55a", _c
    assert _decrypt_block(bytes.fromhex(_c), _expand_key(_k)) == _p
    if len(sys.argv) == 2:
        rec = read_from_file(sys.argv[1])
        print(rec if rec else "(none)")
    else:
        print("AES self-test OK.  usage: python fzmeta.py <fused.exe>")
