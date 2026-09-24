#!/usr/bin/env python3
"""postflash_vcn_check: did the route-B BIOS driver enable the VCN hardware?

Re-reads the probe4l6 address set (baseline 2026-09-24 01:27, stock BIOS)
plus every direct driver-write target (bitmap, trigger, enable block),
diffs against the baked baseline, and prints a verdict. Safe: Q3 0x2A
reads of MMIO data addresses only (the class probe4l6/4l7 ran all night);
no writes, no code-space reads.

Run on the board after a route-B flash (v005/v007/v008 ladder) + Linux boot:
    sudo python3 postflash_vcn_check.py
NOTE: push this exact repo revision to the board on the next Linux boot
before interpreting results; the on-board copy may be older.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.environ.get(
    "BC250_SMU_PATH", "/home/steammachine/vcn_unlock/bc250-smu-unlock"))
from bc250_smu import Bc250Smu  # noqa: E402

# name -> (address, pre-flash baseline value from probe4l6)
BASE = {
    "en_808":        (0x0115F808, 0x00000002),  # driver: RMW |= 1 -> expect bit0
    "pstep19_8fc":   (0x0115F8FC, 0x00000000),  # driver: = 0x3F -> expect nonzero
    "pstep19_ack":   (0x0115F920, 0x00000000),  # poll & 0x10000 -> expect bit set
    "pstep1a_924":   (0x0115F924, 0x00000000),  # driver: = 0x3F -> expect nonzero
    "pstep1a_ack":   (0x0115F948, 0x00000000),  # poll & 0x10000 -> expect bit set
    "vcn_358":       (0x0115F958, 0x00000000),  # driver: = 0x10000
    "vcn_35c":       (0x0115F95C, 0x00000000),  # driver: RMW |= 0x4C000
    "gate_320":      (0x0115A320, None),        # driver: RMW &= ~2 (no baseline)
    "gate_330":      (0x0115A330, None),        # driver: RMW = (r&~0xE)|1
    "gate_32c":      (0x0115A32C, None),        # driver: RMW = (r&~7)|0x17
    "gate_334":      (0x0115A334, None),        # driver: RMW |= 0x30
    "gate_338":      (0x0115A338, None),        # driver: RMW |= 1 (final gate)
    "bitmap_ccb8":   (0x0000CCB8, None),        # driver: RMW |= 0x40 (permission)
    "trig_218":      (0x0115F818, None),        # driver: = 1 (PLL trigger)
    "ctl_374":       (0x0115F974, None),        # driver: = 0 (tail write)
    "enblk_204":     (0x0100B004, None),        # driver: = 1
    "enblk_208":     (0x0100B008, None),        # driver: = 1
    "enblk_2e0":     (0x0100B2E0, None),        # driver: = 0xF
    "enblk_00c":     (0x0100B00C, 0x75767570),  # driver: = 0x75767570 (exact)
    "enblk_034":     (0x0100B034, None),        # driver: RMW |= 1 + poll bit2
    "dclk_prog":     (0x0116D100, 0x00000000),  # clock programming -> nonzero
    "vclk_prog":     (0x0116D128, 0x00000000),
    "dclk_ack":      (0x0116D114, 0x00000000),
    "vclk_ack":      (0x0116D13C, 0x00000000),
    "ctl_200":       (0x0115F800, 0x0000000E),  # boot-programmed config word
}
# markers that PROVE the driver's replay ran (bit test, baseline, mask)
MARKERS = {
    "en_808":      (0x00000002, 0x00000001),   # bit0 newly set
    "pstep19_8fc": (0x00000000, None),         # any nonzero
    "pstep1a_924": (0x00000000, None),
    "pstep19_ack": (0x00000000, 0x00010000),
    "pstep1a_ack": (0x00000000, 0x00010000),
    "vcn_358":     (0x00000000, 0x00010000),
    "vcn_35c":     (0x00000000, 0x0004C000),
    "dclk_prog":   (0x00000000, None),
    "vclk_prog":   (0x00000000, None),
    "bitmap_ccb8": (0x00000000, 0x00000040),   # permission bit6 set
    "trig_218":    (0x00000000, 0x00000001),   # trigger written
    "enblk_204":   (0x00000000, 0x00000001),
    "enblk_208":   (0x00000000, 0x00000001),
    "enblk_2e0":   (0x00000000, 0x0000000F),
    "enblk_00c":   (0x75767570, "EQ"),      # F8: exact equality, not mask
    "enblk_034":   (0x00000000, 0x00000001),   # our bit0 (bit2 = handshake)
}


def main() -> int:
    s = Bc250Smu()
    out = {"tool": "postflash_vcn_check", "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    alive = s.alive()
    print("alive:", alive)
    st, ver = s.send_message(0, 0x02)
    out["smu_version"] = "0x%08x" % ver
    out["transport_alive"] = bool(alive)
    print("SMU: 0x%08x" % ver)
    if not alive:
        # F11: a dead transport is not "driver did nothing" — say so.
        out["verdict"] = "TRANSPORT_DEAD (mailbox silent, cannot judge driver)"
        print("\nVERDICT:", out["verdict"])
        with open("/tmp/postflash-vcn-check.json", "w") as f:
            json.dump(out, f, indent=2)
        return 0
    reads, passed, failed = {}, [], []
    for name, (addr, base) in BASE.items():
        st, val = s.send_message(3, 0x2A, [addr])
        reads[name] = "0x%08x" % val
        line = f"  {name:14s} @0x{addr:08x} = 0x{val:08x}"
        if base is not None:
            line += f"  (was 0x{base:08x})"
        print(line)
        if name in MARKERS:
            old, mask = MARKERS[name]
            if mask == "EQ":
                ok = (val == old)
            else:
                ok = (val != 0) if mask is None else bool(val & mask)
            (passed if ok else failed).append(name)
    s.close()
    out["reads"] = reads
    out["markers_passed"] = passed
    out["markers_failed"] = failed
    n = len(passed)
    # F10: route-B invariant — the boot config word 0x0115F800 must still be
    # 0x0E. If the driver (or a 0x1B-class corruption) zeroed it, ENABLED is
    # forbidden no matter how many markers passed.
    ctl_ok = reads.get("ctl_200") == "0x0000000e"
    if not ctl_ok:
        failed.append("GUARD-ctl_200-VIOLATED")
    # 16 markers (9 original + 7 driver-write proofs); thresholds scaled from
    # the original 6/9 and 3/9 by the same ~2/3 and ~1/3 ratios.
    if "en_808" in passed and n >= 10 and ctl_ok:
        verdict = "VCN_HARDWARE_ENABLED"
    elif n >= 5:
        verdict = "PARTIAL (%d/%d markers)" % (n, len(MARKERS))
        if not ctl_ok:
            verdict += " [GUARD-ctl_200-VIOLATED blocks ENABLED]"
    else:
        verdict = "NO_CHANGE (driver did not run or bailed)"
    out["verdict"] = verdict
    print("\nVERDICT:", verdict)
    print("passed:", passed)
    print("failed:", failed)
    with open("/tmp/postflash-vcn-check.json", "w") as f:
        json.dump(out, f, indent=2)
    print("saved /tmp/postflash-vcn-check.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
