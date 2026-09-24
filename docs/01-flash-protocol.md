# Safe EEPROM flash protocol

The procedure behind every flash in this project. It has caught a wrong-chip
state, an NVRAM drift, and a stale checksum before they could do harm.

## Non-negotiables (all four, every time)

1. A full verified dump of YOUR chip (double read, `cmp` match).
2. An independently confirmed recovery path (a known-booting image + the
   exact write command to get it back on).
3. Explicit approval for the exact image (sha256) and target.
4. A cold-boot + readback check planned for after.

No recovery path, no flash.

## The sequence

```sh
# 0. Board FULLY unpowered. Clip on the W25Q128, programmer attached.
# 1. Chip identity (must say W25Q128):
flashrom -p ch347_spi --flash-name
# 2. Fresh DOUBLE read, compare, hash. Expect the image you think is on chip.
flashrom -p ch347_spi -r pre-a.bin
flashrom -p ch347_spi -r pre-b.bin
cmp pre-a.bin pre-b.bin && sha256sum pre-a.bin
#    Mismatch vs expectation (e.g. NVRAM drift from boot attempts)?
#    STOP, diff it, understand it, re-approve. Never auto-continue.
# 3. Package integrity:
sha256sum -c SHA256SUMS
# 4. Write slow and verify (1.875M proved reliable here):
flashrom -p ch347_spi:spispeed=1.875M -w IMAGE.bin   # expect VERIFIED, rc=0
# 5. INDEPENDENT readback + byte compare + hash:
flashrom -p ch347_spi:spispeed=1.875M -r post.bin
cmp post.bin IMAGE.bin && sha256sum post.bin
# 6. Re-parse the READBACK (not the candidate): LZMA header explicit,
#    FV walk clean, driver FFS present. Only then: operator cold boot.
```

## Why each step exists

- Double read: a flaky clip corrupts silently; two agreeing reads don't.
- Expectation check: the board writes NVRAM on boot attempts (we measured
  62 bytes after the FIXED build hangs). A changed chip is information, not an error —
  but it needs a conscious decision.
- Slow write: 15 MHz reads fine; writes at 15 MHz flaked, 1.875M never has.
- Readback, not trust: `flashrom -w` already verifies, and we still re-read
  with a separate command and re-parse the structure. Two independent
  confirmations beat one.

## Recovery

Keep the last known-booting full image plus its sha256 on the flashing host
at all times. Recovery is the same sequence with that image. After any
recovery flash: cold boot, signs (blinks/video/LAN/SSH), readback compare.
