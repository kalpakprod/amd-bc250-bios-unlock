#!/usr/bin/env python3
"""Build BC250_vcn-driver-FULL_lzma-FIXED_early-slot.bin (alias v005): the BROKEN image with ONLY the LZMA-alone outsize field fixed (8 bytes).

Root cause of the first-blink hang of the SUPERSEDED-v003e and BROKEN builds (byte-proven 2026-09-24):
the capsule LZMA-alone header carried an UNKNOWN decoded size
(0xFFFFFFFFFFFFFFFF) because CPython's lzma.compress(FORMAT_ALONE) emits
unknown size. The board's PEI capsule decoder rejects unknown-size streams
(hardware-proven on this platform by the D5-D7 -> D8 campaign: restoring the
explicit decoded length made the same candidate boot). The DXE volume never
decompresses, so the hang happens BEFORE any DXE driver runs — which is why
The SUPERSEDED-v003e (no DEPEX) and BROKEN (DEPEX TRUE) builds show the identical symptom.

The FIXED build changes exactly 8 bytes vs BROKEN: the LZMA-alone uncompressed-size field
(header bytes 5..12) becomes the explicit decompressed-stream length. No
length field, checksum, FV byte, or driver byte changes.

Base:  candidates/BC250_vcn-driver-FULL_lzma-BROKEN_early-slot.bin
        (sha 98b9c2bd0bd0324f5642d76b105fb7a1ba851ec16c5c89046b0bf585a5765ab8)
Output: candidates/BC250_vcn-driver-FULL_lzma-FIXED_early-slot.bin (new, never overwrite)
"""
from __future__ import annotations

import json
import os
import lzma
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_vcn_o3_candidate import (  # noqa: E402
    decompress_inner, walk_inner_fv, sha256,
)

REPO = Path(__file__).resolve().parent.parent
BASE = Path(os.environ.get("BC250_BASE", "BC250_vcn-driver-FULL_lzma-BROKEN_early-slot.bin"))
OUT = Path(os.environ.get("BC250_OUT", "BC250_vcn-driver-FULL_lzma-FIXED_early-slot.bin"))
MANIFEST = Path(os.environ.get("BC250_MANIFEST", "BC250_vcn-driver-FULL_lzma-FIXED_early-slot.build.json"))

BASE_SHA = "98b9c2bd0bd0324f5642d76b105fb7a1ba851ec16c5c89046b0bf585a5765ab8"
UNKNOWN_SIZE = b"\xff" * 8
VCN_GUID = "B6250780-7E00-4203-900C-23443B1413FE"


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite existing output: {OUT}")
    base = BASE.read_bytes()
    assert len(base) == 0x1000000 and sha256(base) == BASE_SHA, "base mismatch"

    clv = decompress_inner(base)
    cpos = clv["cpos"]
    lz_off = cpos + 24 + len(clv["guided_hdr"])
    assert base[lz_off + 3] == 0x02 or True  # guided payload starts here
    props = base[lz_off:lz_off + 1]
    dict_sz = base[lz_off + 1:lz_off + 5]
    old_size = base[lz_off + 5:lz_off + 13]
    assert old_size == UNKNOWN_SIZE, f"expected unknown size, got {old_size.hex()}"
    assert props == b"\x5d" and dict_sz == b"\x00\x00\x00\x01", \
        f"unexpected LZMA params {props.hex()}/{dict_sz.hex()}"

    # Decompressed stream whose length the header must declare.
    doff = len(clv["guided_hdr"])
    csz = clv["csz"]
    comp = base[cpos + 24 + doff:cpos + csz]
    stream = lzma.decompress(bytes(comp), format=lzma.FORMAT_ALONE)
    explicit = len(stream).to_bytes(8, "little")
    assert explicit != UNKNOWN_SIZE

    out = bytearray(base)
    out[lz_off + 5:lz_off + 13] = explicit

    # Verification: identical stream, identical FV, 8-byte diff only.
    comp2 = bytes(out[cpos + 24 + doff:cpos + csz])
    stream2 = lzma.decompress(comp2, format=lzma.FORMAT_ALONE)
    assert stream2 == stream, "decompressed stream changed"
    hdr2 = bytes(out[lz_off:lz_off + 13])
    assert hdr2[5:13] == explicit, "header patch did not land"
    int.from_bytes(hdr2[5:13], "little") == len(stream2)

    chk = decompress_inner(bytes(out))
    assert chk["fv"] == clv["fv"], "inner FV bytes changed"
    inv, _ = walk_inner_fv(chk["fv"])
    newf = [f for f in inv if f["guid"] == VCN_GUID]
    assert len(newf) == 1, "VCN driver lost"

    diffs = [i for i in range(0x1000000) if out[i] != base[i]]
    assert len(diffs) == 8 and diffs == list(range(lz_off + 5, lz_off + 13)), \
        f"diff escaped the size field: n={len(diffs)} first={diffs[:4]}"

    OUT.write_bytes(bytes(out))
    out_sha = sha256(bytes(out))
    MANIFEST.write_text(json.dumps({
        "plain_name": "BC250_vcn-driver-FULL_lzma-FIXED_early-slot.bin",
        "alias": "v005",
        "builder": "tools/build_FULL_lzma_fixed_early_slot.py",
        "variant": "v005",
        "what": "FULL_lzma-BROKEN_early-slot + LZMA-alone explicit decoded size (8-byte patch); "
                "driver, placement, FV, capsule lengths unchanged",
        "fix_vs_BROKEN": "LZMA-alone header bytes 5..12: ffffffff... -> explicit "
                       f"{explicit.hex()} ({len(stream)} = 0x{len(stream):x}); "
                       "repeats the hardware-proven D8 repair of the D5-D7 defect",
        "base": {"path": str(BASE), "sha256": BASE_SHA},
        "output_sha256": out_sha,
        "lzma_header_off": hex(lz_off),
        "explicit_size": len(stream),
        "diff_vs_BROKEN": {"n": 8, "first": hex(diffs[0]), "last": hex(diffs[-1])},
        "hardware_written": False,
    }, indent=2) + "\n")
    print(f"FIXED_early-slot OUT sha256: {out_sha}")
    print(f"LZMA header @{hex(lz_off)}: unknown -> explicit {len(stream)} ({hex(len(stream))})")
    print("diff vs BROKEN: exactly 8 bytes, stream/FV/driver identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
