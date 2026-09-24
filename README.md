**English** | [Русский](README.ru.md)

<p align="center">
  <img src="docs/assets/hero.svg" width="100%" alt="AMD BC-250 BIOS unlock: the VCN encode block, enabled in firmware. Proof panel: LZMA header fixed from unknown size to explicit, ladder v005 DXE boots, v006r on chip.">
</p>

<p align="center">
  <a href="https://github.com/kalpakprod/amd-bc250-bios-unlock/releases"><img src="https://img.shields.io/github/v/release/kalpakprod/amd-bc250-bios-unlock" alt="release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/kalpakprod/amd-bc250-bios-unlock" alt="license"></a>
  <a href="https://github.com/kalpakprod/amd-bc250-bios-unlock"><img src="https://img.shields.io/badge/board-ASRock_BC--250-blue" alt="board"></a>
</p>

## What this is

- This project enables the VCN encode block in the ASRock BC-250 BIOS.
- Method: UEFI/DXE patches, a custom DXE driver, reproducible image builders,
  a 10-gate static preflight, and a safe EEPROM flash protocol.
- Every claim below is verified on real hardware with a programmer.
- Status on 2026-09-24: the LZMA root cause is fixed and hardware-confirmed.
- The remaining DXE wedge is bisected down a 5-rung ladder, one variable at a time.

## Flashing can brick your board

- Every image here is experimental.
- Flashing needs a hardware programmer (CH341/CH347 + SOIC clip).
- Flashing needs a full verified dump of YOUR chip and a tested recovery path.
- Without a recovery path, do not flash.
- Full procedure: [docs/01-flash-protocol.md](docs/01-flash-protocol.md).

## The ladder

How to read a version name:

- `vNN` is the chronological experiment number (v004 came before v005).
- `r` means rebuild: same experiment, fixed bytes (v006r replaces v006).
- The word is the code variant: `noop` does nothing, `active` runs the full
  sequence, `secure` reads safely only, `rtb` defers to ReadyToBoot.
- `ownfv-insert` vs `append` is the placement inside the firmware volume.
- A rung is one image plus its verdict. Verdicts: `flashed` (tried on the
  board), `staged` (built and statically verified, never flashed), `on chip`
  (flashed, verdict pending), `hangs` (tried, board stalled).

The rungs (images + manifests in [Releases](https://github.com/kalpakprod/amd-bc250-bios-unlock/releases)):

- **v004** (`98b9c2bd…`), the LZMA-bug specimen: carries the route-B driver
  with an unknown-size LZMA header. It proves the hang class. Verdict: flashed, hangs after 1 blink.
- **v005** (`2fadb173…`), the DXE-loader: v004 plus an 8-byte LZMA fix.
  It proves the board loads DXE again. Verdict: flashed, hangs after 2 blinks, no LAN/video.
- **v006r-noop** (`6500bea5…`), the control stub: the driver loads but executes
  zero hardware operations. It separates driver guilt from FV-surgery guilt.
  Verdict: on chip, cold-boot signs pending.
- **v007-active** (`9d249397…`), the position test: the full driver appended at
  the volume end instead of inserted early. It tests dispatch position.
  Verdict: staged, flashes if v006r boots.
- **v007r-noop** (`0133a34b…`), the append control: the stub appended at the
  volume end. It isolates insert-position vs append. Verdict: staged, flashes if v006r hangs.
- **v008-secure** (`c935e3ec…`), the safe reader: bitmap via Q3 secure read,
  raw debug reads deleted. It tests whether raw reads were the wedge.
  Verdict: staged, flashes if v006r boots and v007 hangs.
- **v009-rtb** (`56df6244…`), the deferred run: the sequence fires on
  ReadyToBoot, after every driver connects. It tests dispatch timing.
  Verdict: staged, flashes if v006r boots and v007+v008 hang.

## Reproduce in 5 minutes (no hardware)

- Download the v1.0.0 attachments (the v004 image at minimum).
- Rebuild v005 and v006r byte-identically:

```sh
PYTHONPATH=tools python3 tools/build_v005_lzma_explicit.py
# -> 2fadb173251eb4a44aa9da371f37207efb0f276f8d509926083bfa5a64c03406
PYTHONPATH=tools python3 tools/build_v006_noop.py
# -> 6500bea5b01ea1dcc540939d65faa9cc0ec0f2505a5fcb3e358622803b85bb27
```

- Watch v004 FAIL the preflight LZMA gate while v005 passes it:

```sh
python3 tools/verify_candidate_preflight.py --help
```

- With your own 16 MiB dump (`BC250_BASE`, `BC250_PRE_SHA`), the append
  builders (v007–v009) run against YOUR base.
- Never flash anyone's dump, because NVRAM and board data differ.

## Scale of the work

- Active since 2026-09-02 (first message): day 23 of daily work and counting.

![project timeline](docs/assets/timeline.svg)

- Built: 60+ firmware images, 10+ verified flash cycles, each with an
  independent readback.
- Written: 60+ builder/parser/probe scripts, an 83-test gate, 350+ research
  notes, 400+ dated lab-log entries.
- Chain per image: static preflight, OVMF contract run, flash, readback,
  cold-boot verdict. Nothing is called done without evidence.

## Where the ideas came from

- The board itself ships community DXE drivers (`MeiMeiDXEv3_SMU_Core_Unlock`,
  `SMU_Patch`) in our size class. In-UEFI unlock drivers on this exact board
  are proven ground.
- The D-series SMU campaigns (d5–d19) proved three facts: an early-DXE SMU
  touch boots (D10R), an unknown-size LZMA header kills the boot (D5–D7, fixed
  in D8), and single gasket writes wedge the SMU (D12–D19).
- The USB/Linux probes (probe1–probe4) proved one rule: a raw `0xB8/0xBC` read
  of the clock-plan/SMU set wedges the board even after full init. Our driver
  therefore touches raw only mailbox addresses and reads everything else via
  Q3 `0x2A`.
- The community mapped the territory first:
  [bc250-collective/amd_smu_reverse_engineering](https://github.com/bc250-collective/amd_smu_reverse_engineering),
  [thelamer/bc250-vcn](https://github.com/thelamer/bc250-vcn),
  [Shalasere/bc250-vcn-research](https://github.com/Shalasere/bc250-vcn-research),
  [MTSistemi/bc250-vaapi](https://github.com/MTSistemi/bc250-vaapi),
  [Hexxeh/bc250-efi-core-unlock](https://github.com/Hexxeh/bc250-efi-core-unlock).

## What we hit (the wall, honestly)

- **LZMA unknown-size hang.** Our capsule recompressor (Python `lzma`,
  `FORMAT_ALONE`) wrote header size `0xFFFFFFFFFFFFFFFF`. The board's PEI
  decoder rejects unknown size, so the DXE volume never loads. Symptom: first
  blink, then nothing, before any driver runs. Fixed with 8 bytes in v005;
  full story: [docs/05-lzma-lesson.md](docs/05-lzma-lesson.md).
- **DXE wedge ladder.** With DXE loading, the board stalls before video and
  LAN. Suspects in test order: driver code vs FV surgery, then position, then
  raw reads, then timing. Each rung changes exactly one variable.
- **Dispatch position.** Our first slot was the FIRST TRUE-pool driver, ahead
  of PCI, video, LAN, and all AMD chipset DXE. `DEPEX TRUE` changes nothing
  vs no DEPEX (PI spec); the identical v003e/v004 hangs proved it. Map:
  [docs/02-uefi-layout.md](docs/02-uefi-layout.md).

## Layout

- `tools/` holds reproducible builders, the 10-gate preflight, the OVMF driver
  harness, and the post-flash VCN check. Start here:
  [tools/README.md](tools/README.md).
- `src/Bc250VcnUnlockDxe/` holds the DXE driver sources (route-B, secure,
  ReadyToBoot) plus the EDK2 build recipe.
- `docs/` holds the flash protocol, the UEFI layout, the driver write set, the
  VCN check method, and the LZMA lesson.

## We need help with

- **The DXE wedge.** v005 stalls before video and LAN. The write-set vs
  ownership analysis is in `docs/03-route-b-driver.md`. A second pair of eyes
  on the SMU-concurrency mechanism (or a UART mod for POST codes) unblocks us.
- **Linux-side VCN.** When a rung boots, `tools/postflash_vcn_check.py` judges
  the hardware. Review the 16 markers and the amdgpu/VCN bind path.
- **Hardware testers.** BC-250 plus SPI programmer owners who flash staged
  rungs with readback. The ladder is designed for exactly that.
- **History.** We hold 60+ older images (D-series, OC, APCB) with thin
  manifests. Help maps orphan to script to verdict.
- Contact: GitHub issues on this repo. PRs take scripts and docs; full dumps
  are rejected by `.gitignore`.

## License and disclaimer

- Code and docs are MIT.
- The 16 MiB images also contain vendor firmware (AMI/AGESA/PSP blobs) from
  their donor board. Treat them as research artifacts for hardware you own,
  with no warranty.
- Flashing can brick your board, so the recovery path in
  [docs/01-flash-protocol.md](docs/01-flash-protocol.md) is mandatory, not optional.
