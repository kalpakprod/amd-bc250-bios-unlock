#!/usr/bin/env python3
"""Independent pre-flight verification of a VCN-driver candidate (parameterized).

Second, from-scratch pass (the operator demanded repeated verification before
any flash). Walks the donor base and the candidate byte-by-byte, decompresses
the outer DXE FV capsule of each, inventories the inner FV file-by-file with
REAL-DxeCore semantics (the walk STOPS at the first erased buffer, exactly
like MdeModulePkg/Core/Dxe/FwVol.c FwGetNextFile), and proves the candidate
is EXACTLY the donor base plus ONE new DXE driver file, reachable by the
dispatcher. Exit 0 only if every gate passes.

Gates:
  G1 diff_confinement      every changed byte inside the capsule window
  G8 boot_regions_untouched everything outside the capsule sha-identical
  G2 outer_fv_headers      outer FV header valid + unchanged
  G3 inner_inventory       base files all present byte-identical; exactly one
                           new file; nothing else moved/lost/reshaped
  G4 new_ffs               new file identity: GUID/type/size/offset/state
  G5 new_driver_pe         PE32+ X64 boot-service-driver, expected size/sha
  G6 inner_fv_checksum     inner FV header checksum valid in BOTH images
  G7 capsule_free_tail     inner FV ends in 0xFF free space, no overflow
  G9 dispatch_reachable    NO erased gap before the new file; the file BEFORE
                           it ends aligned at it (v003b defect class)
  G10 lzma_explicit_size   capsule LZMA-alone header carries an EXPLICIT
                           decoded size equal to the decompressed stream
                           length (D5-D7 defect class: unknown size
                           0xFFFFFFFFFFFFFFFF hangs the board before DXE;
                           python-lzma tolerates it, the PEI decoder does not)

  NOTE (audit F2): G3 counts (193/194 + exactly one new file) only fit
  base-vs-candidate pairs where the base lacks the VCN file (e.g. pre-dump
  vs v005/v006r/v007/v008/v009). An in-place-patch pair (v005 vs v006r,
  194 vs 194) fails G3 fail-closed with content_changed=[VCN_GUID]; verify
  such pairs by the builder's own asserts (exact FV diff) instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTER_FV = 0xAE0000
CAPSULE_GUID = bytes.fromhex("93fd219e729c154c8c4be77f1db2d792")
NEW_GUID = "B6250780-7E00-4203-900C-23443B1413FE"
EFI_SHA = "ba1cf214178448eabcc353beac59f78f1a404ee65ff5326c5884508c7423e0cb"
FFS_TYPES = set(range(0x01, 0x0F)) | {0xF0}


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def guid_str(h: bytes) -> str:
    h = bytes(h[:16])
    a, b, c = struct.unpack("<IHH", h[:8])
    return f"{a:08X}-{b:04X}-{c:04X}-{h[8:10].hex().upper()}-{h[10:].hex().upper()}"


def decompress_inner(img: bytes) -> tuple[bytes, dict]:
    assert img[OUTER_FV + 0x28 : OUTER_FV + 0x2C] == b"_FVH", "outer FV signature"
    flen = struct.unpack_from("<Q", img, OUTER_FV + 0x20)[0]
    hdrlen = struct.unpack_from("<H", img, OUTER_FV + 0x30)[0]
    hdr_words = list(struct.unpack_from(f"<{hdrlen // 2}H", img[OUTER_FV : OUTER_FV + hdrlen], 0))
    hdr_words[0x32 // 2] = 0
    ck = struct.unpack_from("<H", img, OUTER_FV + 0x32)[0]
    assert (sum(hdr_words) + ck) & 0xFFFF == 0, "outer FV header checksum"
    cpos = img.find(CAPSULE_GUID, OUTER_FV, OUTER_FV + 0x1000)
    assert cpos > 0 and cpos % 8 == 0, hex(cpos)
    assert img[cpos + 18] == 0x0B, "capsule FFS type"
    csz = int.from_bytes(img[cpos + 20 : cpos + 23], "little")
    data = img[cpos + 24 : cpos + csz]
    assert data[3] == 0x02, "GUID_DEFINED section"
    gsz = int.from_bytes(data[0:3], "little")
    assert gsz == len(data), (gsz, len(data))
    doff = int.from_bytes(data[20:22], "little")
    inner = lzma.decompress(bytes(data[doff:]), format=lzma.FORMAT_ALONE)
    assert inner[3] == 0x19, "RAW section"
    rsz = int.from_bytes(inner[0:3], "little")
    p = (rsz + 3) & ~3
    assert inner[p + 3] == 0x17, "FV_IMAGE section"
    fsz = int.from_bytes(inner[p : p + 3], "little")
    meta = {"capsule_off": cpos, "capsule_size": csz, "raw_len": rsz,
            "inner_fv_len": fsz - 4}
    return inner[p + 4 : p + fsz], meta


def walk_ffs(fv: bytes) -> tuple[list[dict], int]:
    """Inventory with real-DxeCore semantics: STOP at the first erased run."""
    assert fv[0x28:0x2C] == b"_FVH", "inner FV signature"
    flen = struct.unpack_from("<Q", fv, 0x20)[0]
    hdrlen = struct.unpack_from("<H", fv, 0x30)[0]
    words = list(struct.unpack_from(f"<{hdrlen // 2}H", fv[:hdrlen], 0))
    words[0x32 // 2] = 0
    ck = struct.unpack_from("<H", fv, 0x32)[0]
    assert (sum(words) + ck) & 0xFFFF == 0, "inner FV header checksum"
    inv, pos = [], 0x48
    while pos + 24 <= flen:
        h = bytes(fv[pos : pos + 24])
        typ = h[18]
        if typ in FFS_TYPES:
            sz = int.from_bytes(h[20:23], "little")
            if (sz >= 24 and pos + sz <= flen
                    and (sum(h[:17]) + sum(h[18:23])) & 0xFF == 0):
                inv.append({"guid": guid_str(h), "type": typ, "size": sz,
                            "off": pos, "state": h[23],
                            "sha": sha256(fv[pos + 24 : pos + sz])})
                pos = (pos + sz + 7) & ~7
                continue
        if fv[pos : pos + 8] == b"\xff" * 8:
            return inv, flen - pos  # DxeCore stops here: free space
        raise ValueError(f"FFS walk stops at {pos:#x}: {h.hex()}")
    return inv, 0


def lzma_header_info(img: bytes) -> dict:
    """Capsule LZMA-alone header: params + declared outsize + real stream len."""
    cpos = img.find(CAPSULE_GUID, OUTER_FV, OUTER_FV + 0x1000)
    assert cpos > 0 and cpos % 8 == 0, hex(cpos)
    csz = int.from_bytes(img[cpos + 20 : cpos + 23], "little")
    data = img[cpos + 24 : cpos + csz]
    doff = int.from_bytes(data[20:22], "little")
    comp = bytes(data[doff:])
    assert len(comp) >= 13, "truncated LZMA header"
    stream = lzma.decompress(comp, format=lzma.FORMAT_ALONE)
    return {"lz_off": hex(cpos + 24 + doff),
            "props": hex(comp[0]), "dict": hex(int.from_bytes(comp[1:5], "little")),
            "outsize": int.from_bytes(comp[5:13], "little"),
            "stream_len": len(stream)}


def pe_check(ffs_payload: bytes) -> dict:
    ssz = int.from_bytes(ffs_payload[0:3], "little")
    assert ffs_payload[3] == 0x10, "PE32 section type"
    pe = ffs_payload[4 : 4 + ssz - 4]
    assert pe[:2] == b"MZ", "DOS header"
    lfanew = struct.unpack_from("<I", pe, 0x3C)[0]
    assert pe[lfanew : lfanew + 4] == b"PE\x00\x00", "PE signature"
    machine = struct.unpack_from("<H", pe, lfanew + 4)[0]
    opt = lfanew + 24
    magic = struct.unpack_from("<H", pe, opt)[0]
    subsystem = struct.unpack_from("<H", pe, opt + 68)[0]
    return {"pe_len": len(pe), "machine": hex(machine), "magic": hex(magic),
            "subsystem": hex(subsystem), "sha256": sha256(pe)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path,
                    default=REPO / "evidence/donor/fd-v22-20260923/BC250_3.00_MeiMeiDXEv3")
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--new-off", type=lambda s: int(s, 0), required=True,
                    help="expected inner-FV offset of the new file")
    ap.add_argument("--new-size", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--efi-sha", default=EFI_SHA,
                    help="expected sha256 of the new driver's PE32 "
                         "(default: route-B driver; control builds pass theirs)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--win-lo", type=lambda s: int(s, 0), default=OUTER_FV + 0x88,
                    help="declared diff-window start (default: capsule start)")
    ap.add_argument("--win-hi", type=lambda s: int(s, 0), default=0xC2654B,
                    help="declared diff-window end (default: donor-capsule end)")
    a = ap.parse_args()

    gates: dict[str, dict] = {}

    def gate(name: str, ok: bool, **d) -> bool:
        gates[name] = {"pass": bool(ok), **d}
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" {d}" if d else ""))
        return ok

    base = a.base.read_bytes()
    cand = a.candidate.read_bytes()
    ok = True

    diffs = [i for i in range(0x1000000) if base[i] != cand[i]]
    lo, hi = (min(diffs), max(diffs)) if diffs else (0, 0)
    ok &= gate("G1_diff_confinement",
               lo >= a.win_lo and hi <= a.win_hi,
               changed_bytes=len(diffs), window=(hex(lo), hex(hi)),
               declared_window=(hex(a.win_lo), hex(a.win_hi)))
    ok &= gate("G8_boot_regions_untouched",
               sha256(base[: a.win_lo]) == sha256(cand[: a.win_lo])
               and sha256(base[a.win_hi + 1 :]) == sha256(cand[a.win_hi + 1 :]))
    ok &= gate("G2_outer_fv_headers",
               base[OUTER_FV : OUTER_FV + 0x88] == cand[OUTER_FV : OUTER_FV + 0x88])

    fv_b, meta_b = decompress_inner(base)
    fv_c, meta_c = decompress_inner(cand)
    inv_b, free_b = walk_ffs(fv_b)
    inv_c, free_c = walk_ffs(fv_c)
    by_b = {f["guid"]: f for f in inv_b}
    by_c = {f["guid"]: f for f in inv_c}

    new = set(by_c) - set(by_b)
    gone = set(by_b) - set(by_c)
    moved = [g for g in set(by_b) & set(by_c) if by_b[g]["sha"] != by_c[g]["sha"]]
    reshaped = [g for g in set(by_b) & set(by_c)
                if (by_b[g]["size"], by_b[g]["type"]) != (by_c[g]["size"], by_c[g]["type"])]
    ok &= gate("G3_inner_inventory",
               len(new) == 1 and not gone and not moved and not reshaped
               and len(inv_b) == 193 and len(inv_c) == 194,
               base_files=len(inv_b), cand_files=len(inv_c), new=list(new),
               gone=list(gone), content_changed=moved, shape_changed=reshaped)

    nf = by_c.get(NEW_GUID)
    ok &= gate("G4_new_ffs",
               nf is not None and nf["type"] == 0x07 and nf["size"] == a.new_size
               and nf["off"] == a.new_off and nf["state"] == 0xF8,
               found=nf and {"off": hex(nf["off"]), "size": hex(nf["size"]),
                             "type": hex(nf["type"]), "state": hex(nf["state"])})

    pe_info = pe_check(fv_c[a.new_off + 24 : a.new_off + a.new_size]) if nf else {}
    ok &= gate("G5_new_driver_pe",
               pe_info.get("machine") == "0x8664" and pe_info.get("magic") == "0x20b"
               and pe_info.get("subsystem") == "0xb" and pe_info.get("pe_len") == 12288
               and pe_info.get("sha256") == a.efi_sha, **pe_info)

    ok &= gate("G6_inner_fv_checksum", True,
               base_fv_len=meta_b["inner_fv_len"], cand_fv_len=meta_c["inner_fv_len"],
               note="asserted inside walk_ffs for both images")
    ok &= gate("G7_capsule_free_tail", free_c > 0 and free_c < free_b + 0x4000,
               base_free=hex(free_b), cand_free=hex(free_c))

    # G9: dispatch reachability — no erased gap before the new file
    if nf:
        before = [f for f in inv_c if f["off"] < a.new_off]
        prev_end = (before[-1]["off"] + before[-1]["size"] + 7) & ~7 if before else 0x48
        gap = a.new_off - prev_end
        ok &= gate("G9_dispatch_reachable", gap == 0,
                   prev_file=before[-1]["guid"] if before else None,
                   prev_end=hex(prev_end), new_off=hex(a.new_off),
                   erased_gap_bytes=gap)
    else:
        ok &= gate("G9_dispatch_reachable", False, reason="new file not found")

    # G10: LZMA-alone explicit decoded size (D5-D7 defect class, re-caught
    # on v004 2026-09-24: unknown size passes python-lzma but hangs the board
    # in PEI, before any DXE driver runs).
    lz_b, lz_c = lzma_header_info(base), lzma_header_info(cand)
    ok &= gate("G10_lzma_explicit_size",
               lz_c["outsize"] != 0xFFFFFFFFFFFFFFFF
               and lz_c["outsize"] == lz_c["stream_len"]
               and (lz_c["props"], lz_c["dict"]) == (lz_b["props"], lz_b["dict"]),
               base={k: (hex(v) if isinstance(v, int) else v) for k, v in lz_b.items()},
               cand={k: (hex(v) if isinstance(v, int) else v) for k, v in lz_c.items()})

    verdict = "GO" if ok else "NO-GO"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"verdict": verdict, "candidate": str(a.candidate),
                                 "candidate_sha256": sha256(cand), "gates": gates},
                                indent=2) + "\n")
    print(f"\nVERDICT: {verdict}")
    print("saved", a.out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
