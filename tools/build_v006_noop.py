#!/usr/bin/env python3
"""Build v006-noop: v005 with the VCN driver's entry stubbed to return 0.

Diagnostic control (D7 class). v005 loads DXE (two blinks) but stalls before
LAN/video. The capsule change vs the booted dump is the only variable, but
two suspects share it: the driver's VCN writes (fast wedge, D11/D12 class)
vs the FV insertion surgery itself. v006 separates them: the driver FFS
stays at the same offset with the same size, but its code never runs.

Method: patch 3 bytes at the PE entry (file off, computed) to
`33 C0 C3` (xor eax,eax; ret = return EFI_SUCCESS immediately) and refresh
the PE CheckSum field (4 bytes). FV layout, offsets, sizes, file count,
DEPEX section all identical. The capsule is recompressed with the same LZMA
params and an explicit outsize (G10).

If v006 boots to Linux: the driver's writes wedge DXE -> move the sequence
to ReadyToBoot (v007). If v006 hangs identically: the insertion surgery is
at fault -> switch to in-slot PE swap (D-technique) or append-at-end (W9).

Base:  candidates/BC250_pre_dump_vcn_own_fv_v005.bin (2fadb173...)
Output: candidates/BC250_pre_dump_vcn_own_fv_v006_noop.bin (new, never overwrite)
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
BASE = Path(os.environ.get("BC250_BASE", "BC250_pre_dump_vcn_own_fv_v005.bin"))
OUT = Path(os.environ.get("BC250_OUT", "BC250_pre_dump_vcn_own_fv_v006r_noop.bin"))
MANIFEST = Path(os.environ.get("BC250_MANIFEST", "BC250_pre_dump_vcn_own_fv_v006r_noop.build.json"))

BASE_SHA = "2fadb173251eb4a44aa9da371f37207efb0f276f8d509926083bfa5a64c03406"
VCN_GUID = "B6250780-7E00-4203-900C-23443B1413FE"
V005_PE_SHA = "ba1cf214178448eabcc353beac59f78f1a404ee65ff5326c5884508c7423e0cb"
STUB = bytes([0x33, 0xC0, 0xC3])  # xor eax,eax; ret
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA1, "dict_size": 16 * 1024 * 1024,
                 "lc": 3, "lp": 0, "pb": 2, "mode": lzma.MODE_NORMAL,
                 "nice_len": 64, "mf": lzma.MF_BT4}]


def pe_entry_file_offset(pe: bytes) -> tuple[int, int]:
    """Return (entry file offset, checksum field file offset)."""
    assert pe[:2] == b"MZ"
    lfanew = struct.unpack_from("<I", pe, 0x3C)[0]
    assert pe[lfanew:lfanew + 4] == b"PE\0\0"
    coff = lfanew + 4
    nsec = struct.unpack_from("<H", pe, coff + 2)[0]
    optsz = struct.unpack_from("<H", pe, coff + 16)[0]
    opt = coff + 20
    assert struct.unpack_from("<H", pe, opt)[0] == 0x20B, "PE32+ expected"
    entry = struct.unpack_from("<I", pe, opt + 16)[0]
    ckoff = opt + 64
    secoff = opt + optsz
    for _ in range(nsec):
        vsize, vaddr, rawsz, raw = struct.unpack_from("<IIII", pe, secoff + 8)
        if vaddr <= entry < vaddr + vsize:
            foff = raw + (entry - vaddr)
            assert foff + 3 <= len(pe)
            return foff, ckoff
        secoff += 40
    raise AssertionError("entry not inside any section")


def pe_checksum(data: bytes, ckoff: int) -> int:
    """Microsoft PE checksum over data with the CheckSum field treated as 0."""
    s = 0
    n = (len(data) + 1) & ~1
    for i in range(0, n, 2):
        if i == ckoff:
            continue
        w = data[i] if i < len(data) else 0
        if i + 1 < len(data):
            w |= data[i + 1] << 8
        s += w
        s = (s & 0xFFFFFFFF) + (s >> 32)
    s = (s & 0xFFFF) + (s >> 16)
    s = (s & 0xFFFF) + (s >> 16)
    return (s + len(data)) & 0xFFFFFFFF


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite existing output: {OUT}")
    base = BASE.read_bytes()
    assert len(base) == 0x1000000 and sha256(base) == BASE_SHA, "base mismatch"

    clv = decompress_inner(base)
    inv, _ = walk_inner_fv(clv["fv"])
    vcn = [f for f in inv if f["guid"] == VCN_GUID]
    assert len(vcn) == 1
    off, size = vcn[0]["off"], vcn[0]["size"]
    ffs = bytearray(clv["fv"][off:off + size])
    assert ffs[18] == 0x07 and ffs[23] == 0xF8

    # PE32 section is first; patch the entry inside it.
    ssz = int.from_bytes(ffs[24:27], "little")
    assert ffs[27] == 0x10, "PE32 section expected first"
    pe = bytearray(ffs[28:28 + ssz - 4])
    assert len(pe) == 12288 and sha256(bytes(pe)) == V005_PE_SHA
    foff, ckoff = pe_entry_file_offset(bytes(pe))
    assert bytes(pe[foff:foff + 3]) == bytes([0x55, 0x48, 0x89]), \
        f"unexpected entry prologue: {bytes(pe[foff:foff+8]).hex()}"
    pe[foff:foff + 3] = STUB
    struct.pack_into("<I", pe, ckoff, 0)
    struct.pack_into("<I", pe, ckoff, pe_checksum(bytes(pe), ckoff))
    noop_pe_sha = sha256(bytes(pe))

    ffs[28:28 + len(pe)] = pe
    assert len(ffs) == size, "FFS size changed!"
    # F1 (audit 2026-09-24): the stub changes the file body, so refresh the
    # FFS File checksum (byte 17) when the CHECKSUM attribute is set. Formula
    # (validated against the v005 donor): File = -(sum(body)) & 0xFF.
    if ffs[19] & 0x40:
        ffs[17] = (-sum(ffs[24:])) & 0xFF
    assert (sum(ffs[24:]) + ffs[17]) & 0xFF == 0 or not (ffs[19] & 0x40), \
        "FFS File checksum"
    assert (sum(ffs[:17]) + sum(ffs[18:23])) & 0xFF == 0, "FFS header checksum"
    # F3 (audit): assert the DEPEX payload itself, not just the section type.
    body, o = ffs[24:], 0
    depex_payload = None
    while o + 4 <= len(body):
        ssz = int.from_bytes(body[o:o + 3], "little")
        st = body[o + 3]
        if ssz < 4 or o + ssz > len(body):
            break
        if st == 0x13:
            depex_payload = bytes(body[o + 4:o + ssz])
        o += ssz
    assert depex_payload == b"\x06\x08", f"DEPEX payload: {depex_payload!r}"

    new_fv = bytearray(clv["fv"])
    new_fv[off:off + size] = ffs
    fv_bytes = bytes(new_fv)
    assert len(fv_bytes) == len(clv["fv"]), "FV length changed!"
    # FV header checksum still valid (header untouched, but assert anyway).
    hdrlen = struct.unpack_from("<H", fv_bytes, 0x30)[0]
    words = list(struct.unpack_from(f"<{hdrlen // 2}H", fv_bytes[:hdrlen], 0))
    words[0x32 // 2] = 0
    ck = struct.unpack_from("<H", fv_bytes, 0x32)[0]
    assert (sum(words) + ck) & 0xFFFF == 0

    fvim = int.to_bytes(len(fv_bytes) + 4, 3, "little") + b"\x17" + fv_bytes
    stream = clv["raw"] + b"\x00" * clv["raw_pad"] + fvim
    compressed = bytearray(lzma.compress(stream, format=lzma.FORMAT_ALONE,
                                         filters=LZMA_FILTERS))
    # Explicit outsize (G10): the v005 lesson, applied at build time.
    assert bytes(compressed[5:13]) == b"\xff" * 8, "lzma emitted explicit size?"
    compressed[5:13] = len(stream).to_bytes(8, "little")
    assert compressed[0] == 0x5D and bytes(compressed[1:5]) == b"\x00\x00\x00\x01"
    # Round-trip: must decode to the identical stream.
    assert lzma.decompress(bytes(compressed), format=lzma.FORMAT_ALONE) == stream

    guided = bytearray(clv["guided_hdr"])
    new_gsz = len(guided) + len(compressed)
    assert new_gsz < 0xFFFFFF
    guided[0:3] = int.to_bytes(new_gsz, 3, "little")
    new_csz = 24 + len(guided) + len(compressed)
    cpos, old_csz = clv["cpos"], clv["csz"]
    outer_end = OUTER_FV + OUTER_LEN
    assert all(b == 0xFF for b in base[cpos + old_csz:outer_end])
    assert cpos + new_csz <= outer_end
    cap_hdr = bytearray(base[cpos:cpos + 24])
    assert cap_hdr[19] & 0x40 == 0
    cap_hdr[20:23] = int.to_bytes(new_csz, 3, "little")
    ffs_header_checksum(cap_hdr)

    out = bytearray(base)
    out[cpos:cpos + 24] = cap_hdr
    out[cpos + 24:cpos + new_csz] = bytes(guided) + bytes(compressed)
    out[cpos + new_csz:outer_end] = b"\xff" * (outer_end - cpos - new_csz)

    # Verification on the output bytes.
    chk = decompress_inner(bytes(out))
    assert chk["fv"] == fv_bytes, "FV mismatch after round-trip"
    chk_inv, _ = walk_inner_fv(chk["fv"])
    assert len(chk_inv) == len(inv) == 194
    embedded = chk["fv"][off:off + size]
    assert guid_str(embedded) == VCN_GUID and embedded[18] == 0x07
    essz = int.from_bytes(embedded[24:27], "little")
    epe = embedded[28:28 + essz - 4]
    assert sha256(epe) == noop_pe_sha
    efoff, _ = pe_entry_file_offset(epe)
    assert bytes(epe[efoff:efoff + 3]) == STUB, "stub lost in-image"
    diffs = [i for i in range(0x1000000) if out[i] != base[i]]
    assert all(cpos <= i < outer_end for i in diffs), "diff escaped capsule"

    OUT.write_bytes(bytes(out))
    out_sha = sha256(bytes(out))
    MANIFEST.write_text(json.dumps({
        "variant": "v006r-noop",
        "what": "v005 + entry stub (xor eax,eax; ret) in the VCN PE32; same FFS "
                "offset/size, same FV layout, recompressed capsule, explicit LZMA",
        "question": "does DXE complete with a passive driver in this slot?",
        "base": {"path": str(BASE), "sha256": BASE_SHA},
        "output_sha256": out_sha,
        "entry_patch": {"pe_file_off": hex(foff), "old": "554889", "new": "33c0c3",
                        "checksum_refreshed": True},
        "pe": {"len": 12288, "v005_sha": V005_PE_SHA, "noop_sha": noop_pe_sha},
        "injected": {"guid": VCN_GUID, "fv_off": hex(off), "size": hex(size)},
        "diff_window": {"first": hex(min(diffs)), "last": hex(max(diffs)),
                        "ndiff": len(diffs)},
        "capsule": {"old_csz": hex(old_csz), "new_csz": hex(new_csz)},
        "hardware_written": False,
    }, indent=2) + "\n")
    print(f"v006r-noop OUT sha256: {out_sha}")
    print(f"noop PE sha256: {noop_pe_sha}")
    print(f"same FFS @{hex(off)} size {hex(size)}; capsule {hex(old_csz)} -> {hex(new_csz)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
