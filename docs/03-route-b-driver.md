# Route-B driver: write set, variants, rules

`src/Bc250VcnUnlockDxe/` — a DXE driver that replays, from the host side, the
tail of the SMU firmware's own VCN bring-up (message `0x1B` handler body).
Goal: VCN clocks on, power acked, enable block set — the encode block alive.

## The sequence (all via Q3 mailbox `0x2A`, see rules)

1. Bitmap `0x0000CCB8 |= 0x40` (permission bit; SMU reads it only in a tail
   that never runs here — lowest risk).
2. Gate modes `0x0115A320/12C/130/134` + final `0x0115A138 |= 1`.
3. Pre-state read `0x0115F808`; PLL enable `|= 1`, trigger `0x0115F818 = 1`,
   poll ready (125 × 2 ms, fail-fast).
4. Tail `0x0115F958 = 0x10000`, `0x95C |= 0x4C000`, `0x974 = 0`.
5. Power steps `0x8FC/0x924 = 0x3F`, ack polls on `0x920/0x948`.
6. Enable block `0x0100B004/008 = 1`, `0x2E0 = 0xF`, `0x00C = magic`,
   `0x034 |= 1` + handshake poll.
7. Verify: SMU alive + `0x0115F808` bit0. Entry always returns success;
   failures are DEBUG-logged, never fatal to the boot.

## Variants (one variable each)

- `BC250VCNUnlockDxe.c` — route-B baseline (raw bitmap + plan reads).
- `BC250VCNUnlockDxe_secure.c` — bitmap via `0x2A`, 20-read raw plan dump
  deleted (it was DEBUG-only). Every raw touch targets a Q3 register.
- `BC250VCNUnlockDxe_rtb.c` — secure code, entry only registers a one-shot
  ReadyToBoot callback. Zero hardware touches at dispatch.

## Rules learned the hard way

- **Raw `0xB8/0xBC` touches ONLY Q2/Q3 mailbox (`0x03B10Axx`).** A raw read
  of the clock-plan/SMU set wedges the board even after full init (proven by
  probe3). Everything else goes through secure `0x2A`.
- **The SMU is a live agent.** Targets are its own SRAM/state; our writes
  race its boot sequencing. Later dispatch = less race (the v007→v009 logic).
- **Fail fast, fail loud.** Every poll is timeout-bounded (mailbox 5 s,
  registers 125 iters); the driver can stall a boot for seconds, never minutes.
- Build: EDK2 `RELEASE_GCC X64 -Werror`, 12288-byte PE, FFS
  `[PE32 + DXE_DEPEX TRUE]` (PE32 section FIRST — the v003b lesson).

## Open question (help wanted)

Which exact write wedges pre-video DXE? Risk ranking (inference, not yet
hardware-bisected): gate modes > PLL trigger > power steps > enable block >
bitmap. The STUB early-slot verdict picks the next experiment.
