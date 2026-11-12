#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decrypt Meituan Logan (clogan native) log files.

Format reverse-engineered from:
  Logan/Clogan/clogan_core.c   (restore_last_position_clogan / clogan_zlib_end_compress)
  Logan/Clogan/zlib_util.c     (deflateInit2(..., 15+16, ...) -> gzip container)
  Logan/Clogan/aes_util.c      (mbedtls_aes_crypt_cbc, KEY/IV = first 16 bytes)

File layout (repeating "compression units"):

    +--------+------------------+---------------------------+------+
    | 0x01   | content_len (4B) | ciphertext (content_len)  | 0x00 |
    +--------+------------------+---------------------------+------+
      1 byte    big-endian        multiple of 16 bytes       tail

  content_len counts ONLY the ciphertext bytes of the unit.
  Plaintext of the unit = gzip stream + PKCS#7 padding to 16-byte multiple
  (the padding is produced by clogan_zlib_end_compress, val = 16 - remain).

  Encryption: AES-128-CBC, one continuous CBC chain per unit, IV reset to the
  static IV at the start of every unit (init_encrypt_key_clogan()).
  KEY = IV = b"0123456789012345"  (first 16 bytes of "0123456789012345xxx").

Usage:
    python decrypt_logan.py <in.bin> [more.bin ...]      # writes <in>.plain.txt
"""

import gzip
import sys
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

RAW_KEY = b"0123456789012345xxx"
KEY = RAW_KEY[:16]
IV = RAW_KEY[:16]

HDR = 0x01          # LOGAN_WRITE_PROTOCOL_HEADER
TAIL = 0x00         # LOGAN_WRITE_PROTOCOL_TAIL

BLOCK = algorithms.AES(KEY)


def cbc_decrypt(data: bytes, iv: bytes = IV) -> bytes:
    dec = Cipher(BLOCK, modes.CBC(iv)).decryptor()
    return dec.update(data) + dec.finalize()


def strip_pkcs7(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= 16 and data[-pad:] == bytes([pad]) * pad:
        return data[:-pad]
    return data  # not padded (should not happen for clogan units)


def split_units(blob: bytes):
    """Yield (offset, content_len, ciphertext, tail_ok)."""
    off = 0
    n = len(blob)
    while off < n:
        if blob[off] != HDR:
            raise ValueError(f"bad unit header 0x{blob[off]:02x} at offset {off}")
        if off + 5 > n:
            raise ValueError(f"truncated length field at offset {off}")
        clen = int.from_bytes(blob[off + 1:off + 5], "big")
        start = off + 5
        end = start + clen
        if end > n:
            raise ValueError(
                f"truncated unit at offset {off}: need {clen} bytes, have {n - start}"
            )
        if clen % 16:
            raise ValueError(f"content_len {clen} at offset {off} is not a multiple of 16")
        tail_ok = end < n and blob[end] == TAIL
        yield off, clen, blob[start:end], tail_ok
        off = end
        if tail_ok:
            off += 1


def decode_unit(ct: bytes) -> bytes:
    plain = strip_pkcs7(cbc_decrypt(ct))
    # clogan uses windowBits=31 -> gzip container
    if plain[:2] == b"\x1f\x8b":
        return gzip.decompress(plain)
    # be tolerant: raw deflate / zlib fallbacks
    for wbits in (15, -15, 31):
        try:
            return zlib.decompress(plain, wbits)
        except zlib.error:
            pass
    raise ValueError("unit plaintext is neither gzip nor zlib (wrong key/iv?)")


def decrypt_file(path: Path) -> list[str]:
    blob = path.read_bytes()
    units = list(split_units(blob))
    lines: list[str] = []
    for i, (off, clen, ct, tail_ok) in enumerate(units):
        try:
            text = decode_unit(ct).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"### unit {i} @off {off} FAILED: {exc}")
            continue
        if not tail_ok:
            lines.append(f"### unit {i} @off {off}: tail byte missing")
        lines.extend(text.splitlines())
    return lines


def main(argv: list[str]) -> int:
    targets = argv[1:]
    if not targets:
        print(__doc__)
        return 2
    for t in targets:
        src = Path(t)
        out = src.with_suffix(".plain.txt")
        lines = decrypt_file(src)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{src.name}: {len(lines)} lines -> {out}")

        keys = ("activateCode", "LDAC", "ldac", "142", "setActivationLdac",
                "12 0C", "12 0c", "license", "LICENSE")
        hits = [ln for ln in lines if any(k in ln for k in keys)]
        print(f"  keyword hits: {len(hits)}")
        for ln in hits:
            print("   |", ln)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
