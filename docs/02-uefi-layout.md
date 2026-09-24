# UEFI layout of the BC-250 image (16 MiB SPI)

Map of the regions our builders touch. All offsets from our verified dump;
validate against YOUR dump before trusting them.

## Big picture

- Outer SPI: PSP directories, `$PS1` blobs, APCB, UEFI firmware volumes,
  NVRAM (low region, live-writes on boot), padding.
- The DXE volume of interest lives **compressed inside a capsule**: FFS file
  with GUID `93fd219e-729c-154c-8cc4-be77f1db2d792` at outer `0xAE0000`
  (length `0x320000`), LZMA-alone stream, explicit decoded size in the
  13-byte header (`5D <dict:4> <outsize:8>`).
- **We never touch PSP/`$PS1`/signatures.** Every transform changes only the
  capsule window; the preflight gate proves byte-confinement.

## Inner FV (decompressed)

- 193 files in stock form, `0x43D000` bytes; our rungs grow it to `0x440000`
  (append) or `0x441000` (insert), checksums refreshed.
- Order around our slot: `MeiMeiDXEv3_SMU_Core_Unlock @0x3320` → DXE_CORE
  `@0x7068` → **[our driver `@0x12940` in insert rungs]** → BDS → … →
  PciRootBridge `@0x161A88` → GraphicsConsole `@0x1E7FF0` → PciBus
  `@0x20B5F8` → SnpDxe/LAN `@0x222570` → … → free tail.
- The board already ships two community DXE drivers (Core_Unlock +
  SMU_Patch) in our size class — in-UEFI unlock drivers are proven ground.
- Pre-dump also carries GnbDxe/SbDxe/Nbio/Fabric/Agesa DXE after our slot.

## Dispatch lesson (paid for in hardware)

- Our insert slot is the **first TRUE-pool driver**: it runs before PCI,
  video, LAN, and all AMD chipset DXE.
- `DEPEX TRUE` is a scheduling no-op vs no-DEPEX (PI spec: missing DEPEX
  means TRUE). Our SUPERSEDED-v003e→BROKEN "fix" changed nothing — the identical hang on
  both proved it. Appended rungs run last instead; the readyboot build
  defers to ReadyToBoot.
- FV surgery ranking by blast radius: in-slot PE swap (offsets stable) <
  append-at-end (base offsets stable) < insert-before-Bds (shifts ~180 files).
  Our ladder walks this ranking deliberately.
