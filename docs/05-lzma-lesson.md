# The LZMA lesson (8 bytes that ate two flash cycles)

Symptom: board powers, first green blink, then nothing. No second blink, no
LAN, no video. Two different images (v003e without DEPEX, v004 with
`DEPEX TRUE`) hung identically — which already said the driver never ran.

Root cause, byte-proven: our capsule recompressor wrote an LZMA-alone header
with **unknown decoded size**:

```
working dump: 5d 00000001 10d04300 00000000   (explicit 0x43D010)
v004:         5d 00000001 ffffffff ffffffff   (UNKNOWN)
```

CPython's `lzma.compress(FORMAT_ALONE)` emits unknown size by default. Host
Python decompresses it happily — the board's PEI capsule decoder rejects it,
so the DXE volume never loads. The hang sits one layer below the driver.

Fix: patch header bytes 5–12 to the explicit stream length (v005, exactly 8
changed bytes vs v004). Hardware verdict: two blinks — DXE loads. The same
defect class killed the D5–D7 campaign yearside and was fixed the same way
in D8; we repeated history because the lesson lived in prose, not in a gate.

Prevention (shipped in `tools/`): every capsule-recompressing builder emits
explicit size at build time, and preflight gate G10 fails any candidate whose
LZMA outsize is unknown or mismatched. v004 scores NO-GO on G10 alone; v005+
pass 10/10. Demo it yourself with the v1.0.0 attachments (v004 + v005).
