# Post-flash VCN check

`tools/postflash_vcn_check.py` — judges, from Linux, whether the BIOS driver
enabled VCN hardware. Read-only: Q3 `0x2A` reads of MMIO data addresses, no
writes, no code-space reads.

## Markers (16) and guards

Direct driver-write proofs: `en_808` (bit0), power steps + acks (`8FC/920`,
`924/948`), `358/35C`, bitmap bit6, trigger `218`, enable block
(`204/208/2E0/00C-exact/034`), plus consequence markers (`dclk/vclk` prog).
Read-only context: gate modes, `374`, `ctl_200`.

Verdicts:

- `VCN_HARDWARE_ENABLED` — `en_808` + ≥10/16 markers + `ctl_200 == 0x0E`.
- `PARTIAL (n/16)` — some progress; a violated `ctl_200` guard explicitly
  blocks ENABLED and says so.
- `NO_CHANGE` — driver never ran or bailed.
- `TRANSPORT_DEAD` — mailbox silent; the judge abstains instead of guessing.

## Use

On the board after a Linux boot:

```sh
sudo python3 postflash_vcn_check.py   # needs bc250-smu tooling next to it
```

`BC250_SMU_PATH` env points at the `bc250_smu` module (default is the author's
board path). Results also land in `/tmp/postflash-vcn-check.json`.
Self-tested with a mocked mailbox: full-write → ENABLED 16/16, stock →
NO_CHANGE, partial/zeroed-guard/dead-transport → the right verdicts.
