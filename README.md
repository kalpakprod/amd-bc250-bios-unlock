# AMD BC-250 BIOS unlock

Hacking the ASRock BC-250 BIOS toward one goal: **the VCN encode block
enabled in firmware**. UEFI/DXE patches, a from-scratch DXE driver,
reproducible image builders, a strict pre-flight gate, and a safe EEPROM
flash protocol — all verified on real hardware with a programmer.

Status as of 2026-09-24: the LZMA root cause is fixed and hardware-confirmed,
the DXE wedge is being bisected down a 5-rung ladder. `v006r-noop` is on the
chip now; its cold-boot verdict decides the next flash. See [the ladder](#the-ladder).

## Scale of the work

Active since 2026-09-02 (research corpus) / 2026-09-10 (this repo) — day 15
of daily work and counting:

![project timeline](docs/assets/timeline.svg)

- 60+ firmware images built, 10+ verified flash cycles with independent
  readback each.
- 60+ builder/parser/probe scripts, 83-test gate, 350+ research notes,
  400+ dated lab-log entries.
- Full chain per image: static preflight → OVMF contract run → flash →
  readback → cold-boot verdict. Nothing is called done without evidence.

> **Brick warning.** Every image here is experimental. Flashing needs a
> hardware programmer (CH341/CH347 + SOIC clip), a full verified dump of YOUR
> chip, and a tested recovery path. No recovery path, no flash. Details:
> [docs/01-flash-protocol.md](docs/01-flash-protocol.md).

## Where the ideas came from

- **The board itself.** The pre-dump already carries community DXE drivers
  (`MeiMeiDXEv3_SMU_Core_Unlock` + `SMU_Patch`) in the same size class as ours.
  In-UEFI unlock drivers on this exact board are proven ground.
- **D-series SMU campaigns** (d5–d19, our earlier work): proved an early-DXE
  SMU touch boots (D10R), proved the LZMA unknown-size header kills the boot
  (D5–D7 → D8 fix), and mapped which gasket writes wedge the SMU (D12–D19).
- **USB/Linux probes** (probe1–probe4): probe3 proved a raw `0xB8/0xBC` read
  of the clock-plan/SMU set wedges the board even after full init — the rule
  our driver obeys (mailbox addresses only, everything else via Q3 `0x2A`).
- **The community:** [bc250-collective/amd_smu_reverse_engineering](https://github.com/bc250-collective/amd_smu_reverse_engineering)
  (SMU RE bible), [thelamer/bc250-vcn](https://github.com/thelamer/bc250-vcn),
  [Shalasere/bc250-vcn-research](https://github.com/Shalasere/bc250-vcn-research),
  [MTSistemi/bc250-vaapi](https://github.com/MTSistemi/bc250-vaapi),
  [Hexxeh/bc250-efi-core-unlock](https://github.com/Hexxeh/bc250-efi-core-unlock).

## What we hit (the wall, honestly)

1. **LZMA unknown-size hang.** Our capsule recompressor (Python `lzma`,
   `FORMAT_ALONE`) emitted header size `0xFFFFFFFFFFFFFFFF`. The board's PEI
   decoder rejects it: first blink, then nothing — before any DXE runs.
   Byte-proven, hardware-confirmed, fixed with 8 bytes. Full story:
   [docs/05-lzma-lesson.md](docs/05-lzma-lesson.md).
2. **DXE wedge ladder.** With DXE loading, the board stalls before video/LAN.
   Suspects, in test order: driver code vs FV surgery (v006r, on chip) →
   dispatch position (v007) → raw reads (v008) → dispatch timing (v009).
   Each rung changes exactly one variable.
3. **Dispatch position.** Our first slot was the FIRST TRUE-pool driver —
   ahead of PCI, GOP, LAN, and all AMD chipset DXE. Mapped file-by-file:
   [docs/02-uefi-layout.md](docs/02-uefi-layout.md).

## The ladder

| image | sha256 (short) | what | verdict |
|---|---|---|---|
| v004 | `98b9c2bd` | route-B driver, LZMA bug | flashed, 1 blink (specimen) |
| v005 | `2fadb173` | v004 + explicit LZMA size | flashed, 2 blinks, no LAN/video |
| v006r-noop | `6500bea5` | v005 + stubbed entry (control) | **on chip, verdict pending** |
| v007-active | `9d249397` | same driver, appended at FV end | staged |
| v007r-noop | `0133a34b` | noop, appended | staged (if v006r hangs) |
| v008-secure | `c935e3ec` | secure-reads-only driver | staged (if v007 hangs) |
| v009-rtb | `56df6244` | ReadyToBoot-deferred sequence | staged (if v007+v008 hang) |

Images live in [Releases](https://github.com/kalpakprod/amd-bc250-bios-unlock/releases)
as attachments (never in git). Every image: full 16 MiB, built from one
verified dump, published with its `.build.json` manifest and SHA256SUMS.

## Layout

- `tools/` — reproducible builders, the 10-gate preflight, the OVMF driver
  harness, the post-flash VCN check. Start here: [tools/README.md](tools/README.md).
- `src/Bc250VcnUnlockDxe/` — the DXE driver sources (route-B, secure,
  ReadyToBoot) + EDK2 build recipe.
- `docs/` — flash protocol, UEFI layout, driver write set, VCN check method,
  LZMA lesson.

## Reproduce in 5 minutes (no hardware)

```sh
# 1. Grab v1.0.0 attachments (v004 image at least)
# 2. Rebuild v005 and v006r byte-identically:
PYTHONPATH=tools python3 tools/build_v005_lzma_explicit.py
# -> 2fadb173251eb4a44aa9da371f37207efb0f276f8d509926083bfa5a64c03406
PYTHONPATH=tools python3 tools/build_v006_noop.py
# -> 6500bea5b01ea1dcc540939d65faa9cc0ec0f2505a5fcb3e358622803b85bb27
# 3. Watch v004 FAIL the preflight's LZMA gate and v005 pass it:
python3 tools/verify_candidate_preflight.py --help
```

With your own 16 MiB dump (`BC250_BASE`, `BC250_PRE_SHA`), the append
builders (v007–v009) run against YOUR base. Never flash anyone's dump —
NVRAM and board data differ.

## We need help with

Open an issue if you can move any of these:

1. **The DXE wedge.** v005 stalls before video/LAN. Write-set vs ownership
   analysis is in `docs/03-route-b-driver.md`. A second pair of eyes on the
   SMU-concurrency mechanism (or a UART mod to get POST codes!) unblocks us.
2. **Linux-side VCN.** When a rung boots, `tools/postflash_vcn_check.py`
   judges the hardware — review the 16 markers and the amdgpu/VCN bind path.
3. **Hardware testers.** BC-250 + SPI programmer owners willing to flash
   staged rungs with readback — the ladder is designed for exactly that.
4. **History.** We have 60+ older images (D-series, OC, APCB) with thin
   manifests — help mapping orphan → script → verdict.

Contact: GitHub issues on this repo. PRs welcome (scripts and docs; no full
dumps in PRs — see `.gitignore`).

## License and disclaimer

MIT (code and docs). The 16 MiB images additionally contain vendor firmware
(AMI/AGESA/PSP blobs) from the board they were built on — treat them as
research artifacts for hardware you own, with no warranty. Flashing can brick
your board; the recovery path in [docs/01-flash-protocol.md](docs/01-flash-protocol.md)
is mandatory, not optional.
