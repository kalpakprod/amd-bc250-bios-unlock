# Tools

Deterministic, stdlib-only Python (3.10+) plus one shell harness. No
dependencies to install except `flashrom` and (for the OVMF harness) QEMU +
`edk2-ovmf` + `edk2-shell` + `mtools`.

## Builders (each: one input image → one output image + `.build.json`)

| script | input | output | change |
|---|---|---|---|
| `build_FULL_lzma_fixed_early_slot.py` | BROKEN image | FIXED early-slot | LZMA outsize → explicit (8 bytes) |
| `build_STUB_no_hw_ops_early_slot.py` | FIXED image | STUB early-slot | entry stub + FFS checksums |
| `build_FULL_and_STUB_appended_at_end.py --variant active\|noop` | YOUR dump + donor | FULL / STUB appended | append driver at FV end |
| `build_FULL_safe_reads_appended_at_end.py` | YOUR dump + secure.ffs | safe-reads appended | secure-reads driver, appended |
| `build_FULL_deferred_readyboot_appended_at_end.py` | YOUR dump + rtb.ffs | readyboot appended | ReadyToBoot driver, appended |

`build_vcn_o3_candidate.py` is the shared library (capsule parse, FV walk,
checksums) every builder imports. Keep all files in one directory.

Paths are env-overridable (`BC250_BASE`, `BC250_BLOB`, `BC250_DONOR_ACTIVE`,
`BC250_DONOR_NOOP`, `BC250_OUT`, `BC250_MANIFEST`, `BC250_PRE_SHA`); defaults
point at the latest release attachments in the working directory. Builders
refuse to overwrite outputs and assert input identity by sha256 — set
`BC250_PRE_SHA` to YOUR dump's hash; the tools verify the chain from there.

## Gate and harness

- `verify_candidate_preflight.py` — 10 static gates (diff confinement, boot
  regions untouched, FV inventory/checksum, driver PE shape, free tail,
  dispatch reachability, LZMA explicit size). Static GO is necessary, never
  sufficient: it proves well-formed, not bootable.
- `ovmf_driver_test.sh <driver.efi> <label>` — loads a driver in UEFI Shell
  under QEMU, checks load + entry return + shell alive. Proves the binary
  contract only (QEMU has no BC-250 SMU).
- `postflash_vcn_check.py` — the Linux-side VCN judge (see `../docs/04-*.md`).

## Reproduce the release bytes

Download the release attachments, then:

```sh
PYTHONPATH=tools python3 tools/build_FULL_lzma_fixed_early_slot.py  # -> 2fadb173…
PYTHONPATH=tools python3 tools/build_STUB_no_hw_ops_early_slot.py   # -> 6500bea5…
```

Both reproductions are byte-exact against the published shas.
