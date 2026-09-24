#!/usr/bin/env python3
"""Build the two appended-at-end images (aliases v007-active + v007r-noop): full VCN driver and STUB, each APPENDED at the end of the inner FV.

Rationale (2026-09-24 RE): the v005 driver sits at FV 0x12940 as the FIRST
TRUE-pool driver — it runs before PciRootBridge/PciBus, GOP, SnpDxe/LAN and
all AMD chipset DXE (Gnb/Sb/Nbio/Fabric/Agesa). If the STUB early-slot build boots, the
wedge is a dispatch-position problem and the minimal fix is to move the SAME
driver bytes to the END of the FV: all 193 existing files keep their exact
offsets (strictly smaller surgery than insert-before-Bds), and the driver
runs after PCI/video/LAN init.

Variants (one script, --variant):
  active: blob = VCN FFS extracted verbatim from the FIXED early-slot image
          (PE32 sha ba1cf214..., DEPEX TRUE). Output ..._FULL_lzma-FIXED_appended-at-end.bin.
  noop:   blob = VCN FFS extracted verbatim from the STUB early-slot image
          (entry stub, PE32 sha 927e4ef3..., File-checksum fixed per F1).
          Output ..._STUB_no-hw-ops_appended-at-end.bin.
          Needed only if the STUB early-slot build hangs: isolates insert-position vs append.

Base:  evidence/.../pre-v003c-read-a.bin (64973ba364..., the booted dump)
Capsule recompressed with the same LZMA params + explicit outsize (G10).
Outputs are new files, never overwrite.
"""
from __future__ import annotations

import argparse
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
PRE_SHA = os.environ.get("BC250_PRE_SHA", "64973ba364ae4417de10bd905d2cf8bad165af3b544d175b3cc315f0e28d621a")
VCN_GUID = "B6250780-7E00-4203-900C-23443B1413FE"
VARIANTS = {
    "active": (Path(os.environ.get("BC250_DONOR_ACTIVE", "BC250_vcn-driver-FULL_lzma-FIXED_early-slot.bin")),
               "2fadb173251eb4a44aa9da371f37207efb0f276f8d509926083bfa5a64c03406",
               Path(os.environ.get("BC250_OUT", "BC250_vcn-driver-FULL_lzma-FIXED_appended-at-end.bin")),
               Path(os.environ.get("BC250_MANIFEST", "BC250_vcn-driver-FULL_lzma-FIXED_appended-at-end.build.json"))),
    "noop": (Path(os.environ.get("BC250_DONOR_NOOP", "BC250_vcn-driver-STUB_no-hw-ops_early-slot.bin")),
             "6500bea5b01ea1dcc540939d65faa9cc0ec0f2505a5fcb3e358622803b85bb27",
             Path(os.environ.get("BC250_OUT", "BC250_vcn-driver-STUB_no-hw-ops_appended-at-end.bin")),
             Path(os.environ.get("BC250_MANIFEST", "BC250_vcn-driver-STUB_no-hw-ops_appended-at-end.build.json"))),
}
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA1, "dict_size": 16 * 1024 * 1024,
                 "lc": 3, "lp": 0, "pb": 2, "mode": lzma.MODE_NORMAL,
                 "nice_len": 64, "mf": lzma.MF_BT4}]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=("active", "noop"), required=True)
    a = ap.parse_args()
    donor_path, donor_sha, out_path, manifest_path = VARIANTS[a.variant]
    if out_path.exists():
        raise SystemExit(f"refusing to overwrite existing output: {out_path}")

    pre = PRE.read_bytes()
    assert len(pre) == 0x1000000, f"base size must be 16MB, got {len(pre)}"
    assert sha256(pre) == PRE_SHA, ("base sha mismatch: set BC250_PRE_SHA to YOUR dump sha256; "
        f"got {sha256(pre)}")
    donor = donor_path.read_bytes()
    assert sha256(donor) == donor_sha, "donor mismatch"

    # Blob: the exact in-image VCN FFS from the donor (state already 0xF8).
    dclv = decompress_inner(donor)
    dinv, _ = walk_inner_fv(dclv["fv"])
    src = [f for f in dinv if f["guid"] == VCN_GUID]
    assert len(src) == 1
    blob = bytes(dclv["fv"][src[0]["off"]:src[0]["off"] + src[0]["size"]])
    assert blob[18] == 0x07 and blob[23] == 0xF8 and guid_str(blob) == VCN_GUID
    blob_sha = sha256(blob)

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

    # Verification: all 193 base files at IDENTICAL offsets + the append.
    chk = decompress_inner(bytes(out))
    chk_inv, _ = walk_inner_fv(chk["fv"])
    assert len(chk_inv) == len(inv) + 1 == 194
    for f in inv:
        g = [x for x in chk_inv if x["guid"] == f["guid"]]
        assert len(g) == 1 and g[0]["off"] == f["off"] \
            and g[0]["size"] == f["size"] and g[0]["sha"] == f["sha"], f["guid"]
    newf = [x for x in chk_inv if x["guid"] == VCN_GUID]
    assert len(newf) == 1 and newf[0]["off"] == pos \
        and sha256(chk["fv"][pos:pos + len(blob)][24:]) == sha256(blob[24:])
    diffs = [i for i in range(0x1000000) if out[i] != pre[i]]
    assert all(cpos <= i < outer_end for i in diffs), "diff escaped capsule"

    out_path.write_bytes(bytes(out))
    out_sha = sha256(bytes(out))
    manifest_path.write_text(json.dumps({
        "plain_name": out_path.name,
        "alias": f"v007-append-{a.variant}",
        "builder": f"tools/build_FULL_and_STUB_appended_at_end.py ({a.variant})",
        "variant": f"v007-append-{a.variant}",
        "what": f"booted pre-dump + VCN driver ({a.variant}) APPENDED at FV end; "
                "all 193 base files at identical offsets; explicit LZMA",
        "base": {"path": str(PRE), "sha256": PRE_SHA},
        "blob": {"donor": str(donor_path), "donor_sha": donor_sha,
                 "sha256": blob_sha, "size": hex(len(blob))},
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
    print(f"{out_path.name} OUT sha256: {out_sha}")
    print(f"append @{hex(pos)} size {hex(len(blob))}; "
          f"FV {hex(flen)} -> {hex(new_flen)}; base offsets unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
