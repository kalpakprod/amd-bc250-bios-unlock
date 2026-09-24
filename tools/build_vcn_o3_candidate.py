#!/usr/bin/env python3
"""Build Option O3 Monolithic Candidate for BC-250:
1. Removal of PSP lock carriers (entries 0x24 SEC_GASKET and 0x45 TOS_SECURITY_POLICY)
   from the $PSP directory with refreshed Fletcher32 checksum (Lane D).
2. Autonomous pre-OS VCN unlock DXE driver injection into FV_MAIN inner capsule.

Base image: evidence/donor/fd-v22-20260923/BC250_3.00_MeiMeiDXEv3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import struct
from pathlib import Path

# --- Geometry & Constants ---
PSP_DIR = 0x8E0000
EMPTY_ENTRY = b"\xff" * 16
LOCK_TYPES = (0x24, 0x45)

OUTER_FV = 0xAE0000
OUTER_LEN = 0x320000
CAPSULE_GUID = bytes.fromhex("93fd219e729c154c8c4be77f1db2d792")
VCN_GUID = "B6250780-7E00-4203-900C-23443B1413FE"
VCN_NAME = "Bc250VcnUnlockDxe"
STATE_ERASE_POLARITY1 = 0xF8

LZMA_FILTERS = [
    {
        "id": lzma.FILTER_LZMA1,
        "dict_size": 16 * 1024 * 1024,
        "lc": 3,
        "lp": 0,
        "pb": 2,
        "mode": lzma.MODE_NORMAL,
        "nice_len": 64,
        "mf": lzma.MF_BT4,
    }
]

FFS_TYPES = set(
    [
        0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0xF0,
    ]
)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --- PSP Directory Helpers ---
def fletcher32(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    s1 = s2 = 0
    for off in range(0, len(data), 2):
        word = data[off] | (data[off + 1] << 8)
        s1 = (s1 + word) % 65535
        s2 = (s2 + s1) % 65535
    return (s2 << 16) | s1


def dir_count(rom: bytes | bytearray) -> int:
    return struct.unpack_from("<I", rom, PSP_DIR + 8)[0]


def remove_psp_entry(rom: bytearray, ptype: int) -> dict:
    count = dir_count(rom)
    for i in range(count):
        o = PSP_DIR + 0x10 + i * 0x10
        if rom[o] == ptype:
            was = (
                struct.unpack_from("<I", rom, o + 4)[0],
                struct.unpack_from("<I", rom, o + 8)[0],
            )
            rom[o : o + 16] = EMPTY_ENTRY
            return {"index": i, "was_size": was[0], "was_location": hex(was[1])}
    raise SystemExit(f"PSP entry type 0x{ptype:02X} not found")


def refresh_dir_fletcher(rom: bytearray) -> dict:
    count = dir_count(rom)
    end = PSP_DIR + 0x10 + 16 * count
    was = struct.unpack_from("<I", rom, PSP_DIR + 4)[0]
    new = fletcher32(bytes(rom[PSP_DIR + 8 : end]))
    struct.pack_into("<I", rom, PSP_DIR + 4, new)
    return {"was": hex(was), "now": hex(new), "span": [hex(PSP_DIR + 8), hex(end)]}


# --- UEFI FV / FFS Helpers ---
def ffs_header_checksum(header: bytearray) -> None:
    header[16] = 0
    header[16] = (-(sum(header[:16]) + sum(header[18:23]))) & 0xFF


def fv_header_checksum(hdr: bytearray, hdrlen: int) -> None:
    struct.pack_into("<H", hdr, 0x32, 0)
    s = sum(struct.unpack_from(f"<{hdrlen // 2}H", hdr, 0)) & 0xFFFF
    struct.pack_into("<H", hdr, 0x32, (-s) & 0xFFFF)


def guid_str(h: bytes) -> str:
    h = bytes(h[:16])
    a, b, c = struct.unpack("<IHH", h[:8])
    return f"{a:08X}-{b:04X}-{c:04X}-{h[8:10].hex().upper()}-{h[10:].hex().upper()}"


def walk_inner_fv(fv: bytes):
    assert fv[0x28:0x2C] == b"_FVH"
    flen = struct.unpack_from("<Q", fv, 0x20)[0]
    hdrlen = struct.unpack_from("<H", fv, 0x30)[0]
    assert flen <= len(fv)
    inv, pos = [], 0x48
    assert hdrlen == 0x48, hex(hdrlen)
    while pos + 24 <= flen:
        h = bytes(fv[pos : pos + 24])
        typ = h[18]
        if typ in FFS_TYPES:
            sz = int.from_bytes(h[20:23], "little")
            if (
                sz >= 24
                and pos + sz <= flen
                and (sum(h[:17]) + sum(h[18:23])) & 0xFF == 0
            ):
                inv.append(
                    {
                        "guid": guid_str(h),
                        "type": typ,
                        "size": sz,
                        "off": pos,
                        "sha": sha256(bytes(fv[pos + 24 : pos + sz])),
                    }
                )
                pos = (pos + sz + 7) & ~7
                continue
        if bytes(fv[pos : pos + 8]) == b"\xff" * 8:
            pos += 8
            continue
        raise ValueError(f"FFS walk stops at {pos:#x}: {h.hex()}")
    return inv, flen


def decompress_inner(img: bytes):
    cpos = img.find(CAPSULE_GUID, OUTER_FV, OUTER_FV + 0x1000)
    assert cpos > 0 and cpos % 8 == 0
    assert img[cpos + 18] == 0x0B
    csz = int.from_bytes(img[cpos + 20 : cpos + 23], "little")
    data = img[cpos + 24 : cpos + csz]
    assert data[3] == 0x02  # GUID_DEFINED
    gsz = int.from_bytes(data[0:3], "little")
    assert gsz == len(data), (gsz, len(data))
    doff = int.from_bytes(data[20:22], "little")
    inner = lzma.decompress(bytes(data[doff:]), format=lzma.FORMAT_ALONE)
    assert inner[3] == 0x19  # RAW
    rsz = int.from_bytes(inner[0:3], "little")
    p = (rsz + 3) & ~3
    assert inner[p + 3] == 0x17  # FV_IMAGE
    fsz = int.from_bytes(inner[p : p + 3], "little")
    return {
        "cpos": cpos,
        "csz": csz,
        "guided_hdr": bytes(data[:doff]),
        "raw": bytes(inner[:rsz]),
        "raw_pad": p - rsz,
        "fv": bytes(inner[p + 4 : p + fsz]),
    }


def prep_blob(raw: bytes) -> bytes:
    blob = bytearray(raw)
    assert blob[18] == 0x07, f"expected FFS type 0x07 DRIVER, got {blob[18]:#x}"
    assert guid_str(blob) == VCN_GUID, guid_str(blob)
    assert (sum(blob[:17]) + sum(blob[18:23])) & 0xFF == 0, "header checksum bad"
    blob[23] = STATE_ERASE_POLARITY1
    return bytes(blob)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--blob", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()

    base = args.base.read_bytes()
    base_sha = sha256(base)
    assert len(base) == 0x1000000, f"base size must be 16MB, got {len(base)}"

    blob = prep_blob(args.blob.read_bytes())
    blob_sha = sha256(blob)

    # 1. DXE Inner FV injection into capsule
    clv = decompress_inner(base)
    clv_inv, clv_flen = walk_inner_fv(clv["fv"])
    assert not any(f["guid"] == VCN_GUID for f in clv_inv), "VCN GUID already present"

    new_fv = bytearray(clv["fv"][:clv_flen])
    fv_off = len(new_fv)
    new_fv += blob
    while len(new_fv) % 8:
        new_fv += b"\xff"
    new_flen = (len(new_fv) + 0xFFF) & ~0xFFF
    new_fv += b"\xff" * (new_flen - len(new_fv))
    num, blk = struct.unpack_from("<II", new_fv, 0x38)
    assert num * blk == clv_flen, (hex(num), hex(blk), hex(clv_flen))
    assert new_flen % blk == 0
    struct.pack_into("<Q", new_fv, 0x20, new_flen)
    struct.pack_into("<I", new_fv, 0x38, new_flen // blk)
    fv_header_checksum(new_fv, 0x48)

    new_inv, _ = walk_inner_fv(bytes(new_fv))
    assert len(new_inv) == len(clv_inv) + 1, (len(new_inv), len(clv_inv))
    f = [x for x in new_inv if x["guid"] == VCN_GUID]
    assert len(f) == 1 and f[0]["sha"] == sha256(blob[24:])

    fvim = int.to_bytes(len(new_fv) + 4, 3, "little") + b"\x17" + bytes(new_fv)
    stream = clv["raw"] + b"\x00" * clv["raw_pad"] + fvim
    compressed = lzma.compress(
        bytes(stream), format=lzma.FORMAT_ALONE, filters=LZMA_FILTERS
    )
    guided = bytearray(clv["guided_hdr"])
    new_gsz = len(guided) + len(compressed)
    guided[0:3] = int.to_bytes(new_gsz, 3, "little")
    new_csz = 24 + len(guided) + len(compressed)
    cpos, old_csz = clv["cpos"], clv["csz"]
    outer_end = OUTER_FV + OUTER_LEN
    assert all(b == 0xFF for b in base[cpos + old_csz : outer_end]), (
        "non-FF bytes after capsule"
    )
    assert cpos + new_csz <= outer_end, (hex(cpos + new_csz), hex(outer_end))
    cap_hdr = bytearray(base[cpos : cpos + 24])
    assert cap_hdr[19] & 0x40 == 0, "capsule has file checksum; unsupported"
    cap_hdr[20:23] = int.to_bytes(new_csz, 3, "little")
    ffs_header_checksum(cap_hdr)

    out = bytearray(base)
    out[cpos : cpos + 24] = cap_hdr
    out[cpos + 24 : cpos + new_csz] = bytes(guided) + bytes(compressed)
    out[cpos + new_csz : outer_end] = b"\xff" * (outer_end - cpos - new_csz)

    # 2. PSP Directory entry absence (Lane D)
    removed = {f"0x{t:02X}": remove_psp_entry(out, t) for t in LOCK_TYPES}
    flet = refresh_dir_fletcher(out)

    out_sha = sha256(bytes(out))

    # 3. Comprehensive Verification
    chk = decompress_inner(bytes(out))
    chk_inv, chk_flen = walk_inner_fv(chk["fv"])
    assert chk_flen == new_flen
    assert len(chk_inv) == len(clv_inv) + 1
    chk_f = [x for x in chk_inv if x["guid"] == VCN_GUID]
    assert len(chk_f) == 1 and chk_f[0]["sha"] == sha256(blob[24:])

    # Check directory count and removed entries
    cnt = dir_count(out)
    for i in range(cnt):
        o = PSP_DIR + 0x10 + i * 0x10
        assert out[o] not in LOCK_TYPES, f"Lock type 0x{out[o]:02x} still in directory!"
    # Fletcher check
    end = PSP_DIR + 0x10 + 16 * cnt
    flet_check = fletcher32(bytes(out[PSP_DIR + 8 : end]))
    assert flet_check == struct.unpack_from("<I", out, PSP_DIR + 4)[0], "Fletcher32 mismatch"

    # Check byte differences: ONLY in [0x8E0000, 0x8E0140) and [OUTER_FV, OUTER_FV + OUTER_LEN)
    diff_offsets = [i for i in range(len(base)) if base[i] != out[i]]
    for off in diff_offsets:
        in_psp = (0x8E0000 <= off < 0x8E0140)
        in_capsule = (OUTER_FV <= off < OUTER_FV + OUTER_LEN)
        assert in_psp or in_capsule, f"Unexpected diff outside authorized ranges at offset 0x{off:x}"

    print(f"Base SHA256:     {base_sha}")
    print(f"Blob SHA256:     {blob_sha}")
    print(f"Candidate SHA256: {out_sha}")
    print(f"Total diff bytes: {len(diff_offsets)}")
    print(f"PSP Fletcher32:  {flet['was']} -> {flet['now']}")
    print(f"Inner modules:   {len(clv_inv)} -> {len(chk_inv)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bytes(out))

    manifest = {
        "option": "O3",
        "description": "Monolithic candidate: PSP entry absence (0x24/0x45) + autonomous Bc250VcnUnlockDxe",
        "base_image": str(args.base),
        "base_sha256": base_sha,
        "blob": str(args.blob),
        "blob_sha256": blob_sha,
        "output_image": str(args.output),
        "output_sha256": out_sha,
        "psp_entries_removed": removed,
        "psp_fletcher32": flet,
        "dxe_injection": {
            "guid": VCN_GUID,
            "name": VCN_NAME,
            "fv_offset": hex(fv_off),
            "inner_modules_before": len(clv_inv),
            "inner_modules_after": len(chk_inv),
            "inner_fv_length": hex(new_flen),
            "capsule_size": hex(new_csz),
        },
        "diff_byte_count": len(diff_offsets),
        "diff_ranges": [
            "[0x8E0000, 0x8E0140)",
            f"[{hex(OUTER_FV)}, {hex(OUTER_FV + OUTER_LEN)})"
        ],
    }
    args.manifest.write_text(json.dumps(manifest, indent=2))
    print(f"Candidate written to: {args.output}")
    print(f"Manifest written to:  {args.manifest}")


if __name__ == "__main__":
    main()
