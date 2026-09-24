#!/usr/bin/env python3
"""Build BC250_vcn-driver-FULL_deferred-to-readyboot_appended-at-end.bin (alias v009-rtb): full driver firing on ReadyToBoot, APPENDED at the FV end.

Fourth rung of the FIXED-hang ladder (all staged, nothing flashed):
  STUB_early-slot @0x12940   code vs surgery discriminator (on chip, verdict pending)
  FULL_appended             position change, identical code
  safe-reads_appended       same position, secure-reads code
  readyboot_appended        THIS: same position/code, ReadyToBoot timing

The deferred-readyboot driver (BC250VCNUnlockDxe_rtb.c) is the secure-reads code with the
entry point reduced to a one-shot ReadyToBoot registration; the sequence
runs after BDS connects every driver (D9R-proven timing class). Entry does
zero hardware touches. Same FFS size (0x3022), same GUID, DEPEX TRUE.

Flash the readyboot build IF the STUB boots AND FULL-appended + safe-reads both hang: that outcome
isolates dispatch-time writes as the wedge (position fixed, reads fixed,
only timing changes).

Blob: candidates/vcn-unlock-driver-v000-DRAFT/bin/Bc250VcnUnlockDxe-rtb.ffs
Base: evidence/.../pre-v003c-read-a.bin (64973ba364..., the booted dump)
Output: candidates/BC250_vcn-driver-FULL_deferred-to-readyboot_appended-at-end.bin (new)
"""
from __future__ import annotations

import json
import os
import lzma
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_vcn_o3_candidate import (  # noqa: E402
    OUTER_FV, OUTER_LEN, decompress_inner, walk_inner_fv,
    fv_header_checksum, ffs_header_checksum, guid_str, sha256,
)

REPO = Path(__file__).resolve().parent.parent
PRE = Path(os.environ.get("BC250_BASE", "mydump-16m.bin"))
BLOB = Path(os.environ.get("BC250_BLOB", "Bc250VcnUnlockDxe-rtb.ffs"))
OUT = Path(os.environ.get("BC250_OUT", "BC250_vcn-driver-FULL_deferred-to-readyboot_appended-at-end.bin"))
MANIFEST = Path(os.environ.get("BC250_MANIFEST", "BC250_vcn-driver-FULL_deferred-to-readyboot_appended-at-end.build.json"))

PRE_SHA = os.environ.get("BC250_PRE_SHA", "64973ba364ae4417de10bd905d2cf8bad165af3b544d175b3cc315f0e28d621a")
BLOB_SHA = "9393054c63f44fa079455d2908a3132ec1aa725e1ee602e8284806e47343dc26"
VCN_GUID = "B6250780-7E00-4203-900C-23443B1413FE"
SEC_PE_SHA = "b9f11bed66ec96bffd332398deb105e68d6eb4328b319d325a20751acbaab673"
STATE_IN_IMAGE = 0xF8
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA1, "dict_size": 16 * 1024 * 1024,
                 "lc": 3, "lp": 0, "pb": 2, "mode": lzma.MODE_NORMAL,
                 "nice_len": 64, "mf": lzma.MF_BT4}]


def sections_of(ffs: bytes) -> list[tuple[int, int]]:
    body = ffs[24:]
    out, o = [], 0
    while o + 4 <= len(body):
        sz = int.from_bytes(body[o:o + 3], "little")
        t = body[o + 3]
        if sz < 4 or o + sz > len(body):
            break
        out.append((t, sz))
        o += sz
    return out


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite existing output: {OUT}")
    pre = PRE.read_bytes()
    assert len(pre) == 0x1000000, f"base size must be 16MB, got {len(pre)}"
    assert sha256(pre) == PRE_SHA, ("base sha mismatch: set BC250_PRE_SHA to YOUR dump sha256; "
        "got {sha256(pre)}")

    blob = bytearray(BLOB.read_bytes())
    assert sha256(bytes(blob)) == BLOB_SHA, "blob mismatch"
    assert blob[18] == 0x07 and guid_str(blob) == VCN_GUID
    assert (sum(blob[:17]) + sum(blob[18:23])) & 0xFF == 0, "header checksum"
    secs = sections_of(bytes(blob))
    assert [t for t, _ in secs] == [0x10, 0x13], f"sections: {secs}"
    ssz = secs[0][1]
    pe = bytes(blob[28:28 + ssz - 4])
    assert len(pe) == 12288 and sha256(pe) == SEC_PE_SHA, "PE mismatch"
    blob[23] = STATE_IN_IMAGE
    blob = bytes(blob)

    clv = decompress_inner(pre)
    flen = struct.unpack_from("<Q", clv["fv"], 0x20)[0]
    num, blk = struct.unpack_from("<II", clv["fv"], 0x38)
    assert num * blk == flen
    inv, _ = walk_inner_fv(clv["fv"])
    assert not any(f["guid"] == VCN_GUID for f in inv)
    last = max(inv, key=lambda f: f["off"])
    pos = (last["off"] + last["size"] + 7) & ~7
    assert all(b == 0xFF for b in clv["fv"][pos:flen]), "tail not free"

    new_fv = bytearray(clv["fv"][:pos]) + blob
    pad = (8 - (len(new_fv) % 8)) % 8
    new_fv += b"\xff" * pad
    new_flen = (len(new_fv) + blk - 1) & ~(blk - 1)
    new_fv += b"\xff" * (new_flen - len(new_fv))
    struct.pack_into("<Q", new_fv, 0x20, new_flen)
    struct.pack_into("<I", new_fv, 0x38, new_flen // blk)
    fv_header_checksum(new_fv, 0x48)
    new_fv = bytes(new_fv)

    fvim = int.to_bytes(len(new_fv) + 4, 3, "little") + b"\x17" + new_fv
    stream = clv["raw"] + b"\x00" * clv["raw_pad"] + fvim
    compressed = bytearray(lzma.compress(stream, format=lzma.FORMAT_ALONE,
                                         filters=LZMA_FILTERS))
    assert bytes(compressed[5:13]) == b"\xff" * 8
    compressed[5:13] = len(stream).to_bytes(8, "little")
    assert lzma.decompress(bytes(compressed), format=lzma.FORMAT_ALONE) == stream

    guided = bytearray(clv["guided_hdr"])
    new_gsz = len(guided) + len(compressed)
    assert new_gsz < 0xFFFFFF
    guided[0:3] = int.to_bytes(new_gsz, 3, "little")
    new_csz = 24 + len(guided) + len(compressed)
    cpos, old_csz = clv["cpos"], clv["csz"]
    outer_end = OUTER_FV + OUTER_LEN
    assert all(b == 0xFF for b in pre[cpos + old_csz:outer_end])
    assert cpos + new_csz <= outer_end
    cap_hdr = bytearray(pre[cpos:cpos + 24])
    cap_hdr[20:23] = int.to_bytes(new_csz, 3, "little")
    ffs_header_checksum(cap_hdr)

    out = bytearray(pre)
    out[cpos:cpos + 24] = cap_hdr
    out[cpos + 24:cpos + new_csz] = bytes(guided) + bytes(compressed)
    out[cpos + new_csz:outer_end] = b"\xff" * (outer_end - cpos - new_csz)

    chk = decompress_inner(bytes(out))
    chk_inv, _ = walk_inner_fv(chk["fv"])
    assert len(chk_inv) == len(inv) + 1 == 194
    for f in inv:
        g = [x for x in chk_inv if x["guid"] == f["guid"]]
        assert len(g) == 1 and g[0]["off"] == f["off"] \
            and g[0]["size"] == f["size"] and g[0]["sha"] == f["sha"], f["guid"]
    newf = [x for x in chk_inv if x["guid"] == VCN_GUID]
    assert len(newf) == 1 and newf[0]["off"] == pos
    diffs = [i for i in range(0x1000000) if out[i] != pre[i]]
    assert all(cpos <= i < outer_end for i in diffs), "diff escaped capsule"

    OUT.write_bytes(bytes(out))
    out_sha = sha256(bytes(out))
    MANIFEST.write_text(json.dumps({
        "plain_name": "BC250_vcn-driver-FULL_deferred-to-readyboot_appended-at-end.bin",
        "alias": "v009-rtb",
        "builder": "tools/build_FULL_deferred_readyboot_appended_at_end.py",
        "variant": "v009-rtb-append",
        "what": "booted pre-dump + ReadyToBoot VCN driver APPENDED at FV end; "
                "all 193 base files at identical offsets; explicit LZMA",
        "base": {"path": str(PRE), "sha256": PRE_SHA},
        "blob": {"path": str(BLOB), "sha256": BLOB_SHA,
                 "pe_sha256": SEC_PE_SHA},
        "output_sha256": out_sha,
        "inner_fv": {"old_len": hex(flen), "new_len": hex(new_flen),
                     "old_files": len(inv), "new_files": len(chk_inv)},
        "appended": {"guid": VCN_GUID, "fv_off": hex(pos),
                     "size": hex(len(blob))},
        "diff_window": {"first": hex(min(diffs)), "last": hex(max(diffs)),
                        "ndiff": len(diffs)},
        "capsule": {"old_csz": hex(old_csz), "new_csz": hex(new_csz)},
        "hardware_written": False,
    }, indent=2) + "\n")
    print(f"readyboot_appended-at-end OUT sha256: {out_sha}")
    print(f"append @{hex(pos)} size {hex(len(blob))}; "
          f"FV {hex(flen)} -> {hex(new_flen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
