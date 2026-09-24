# Linux kernels for BC-250 VCN work

Two kernel builds plus the mode cmdlines that drive the VCN experiments.
Binaries live in the release attachments; recipe fragments live here.

## Builds

| package | version | sha12 | size | purpose |
|---|---|---|---|---|
| `linux-cachyos-bore-vcn-bc250-7.2.6-1.3` | 7.2.6-1.3 | `d5378b17c442` | 162 M | VCN probe kernel (modes 0/1/2) |
| `...-headers-7.2.6-1.3` | 7.2.6-1.3 | `61abb2d684fe` | 42 M | headers for the probe kernel |
| bore-vcn `vmlinuz` | 7.2.6-1.3 | `713021006a94` | 16 M | raw kernel, boots as-is |
| bore-vcn `initramfs` | 7.2.6-1.3 | `8fe4d5e9fe29` | 56 M | matching initramfs |
| bc250 `vmlinuz` | 7.2.6-1.206 | `4dd8ad294ba3` | 16 M | daily-driver kernel |
| bc250 `initramfs` | 7.2.6-1.206 | `12ec05299f3d` | 56 M | matching initramfs |

File shas above match the hashes recorded in the board's own Limine config,
so these are exactly the binaries the board boots (pulled 2026-09-24).

## Modes (one kernel, three cmdlines)

- `modes/mode0.cmdline` — control: VCN hardware disabled
  (`amdgpu.bc250_vcn_mode=0`).
- `modes/mode1.cmdline` — probe: VCN discovery without hardware access
  (`amdgpu.bc250_vcn_mode=1` + zswap/ppfeaturemask/iommu/cstate tweaks).
- `modes/mode2.cmdline` — hardware: experimental VCN attach
  (`amdgpu.bc250_vcn_mode=2`, amdgpu blacklisted, verbose).
- Mode cmdlines carry this board's snapshot path and UUID: adjust
  `rootflags=`/`root=` to your install.

## Patches (local delta)

- `patches/0008-bc250-40cu.patch` — 40 CU unlock via CC/SPI (by duggasco,
  community; local copy from our build tree).
- `patches/0009-bc250-vcn-safe-direct-load.patch` — `amdgpu_bc250_vcn`
  direct-load flag (local, unattributed).
- Base tree: [MastaG/linux-cachyos-bc250](https://github.com/MastaG/linux-cachyos-bc250)
  (GPL; upstream builds the three kernel families + patched Mesa).
- `scripts/` — the 7.2.0-1.91 probe-kernel installer + boot verifier
  (historical: pins exact package shas, writes the Limine dropin).

## Honest gap

The bore-vcn 1.3 PKGBUILD and the `bc250_vcn_mode` patch source were not
found on the board (build dir cleaned or built elsewhere). Published:
binaries, cmdlines, local patch delta, installer scripts. The build recipe
is wanted: if you hold it, open an issue.
