# Linux kernels and VCN modes

The firmware ladder answers "does DXE survive". The kernels answer "does
VCN exist". Both halves live in this repo since v2.1.0.

## The two builds

- Daily driver: `linux-cachyos-bc250` 7.2.6-1.206. Boots every working
  firmware image in this project. Carries `amdgpu.bc250_cc_write_mode`
  (40 CU control) and the MastaG patch set.
- Probe kernel: `linux-cachyos-bore-vcn-bc250` 7.2.6-1.3 (BORE scheduler).
  Adds the `amdgpu.bc250_vcn_mode=0/1/2` switch. One vmlinuz+initramfs pair
  serves all three modes; only the cmdline differs.

## What each mode proved

- Mode 0 (hardware disabled): the negative control. Boots clean, no VCN.
- Mode 1 (probe, no hardware access): PASS on the 7.2.0-1.91 probe kernel —
  9 IP blocks including `vcn_v2_0_probe`, VCN firmware `ENC 1.24 DEC 8`
  found (`fw_size=404544`). Discovery works; MMIO stays untouched.
- Mode 2 (hardware attach): on 7.2.0-1.91, a controlled probe (boot with
  `modprobe.blacklist=amdgpu`, then manual `modprobe amdgpu`) wedged the
  kernel deterministically at the first VCN hardware access in
  `vcn_v2_0_hw_init`: 10 IP blocks up, SMU 88.6.0 fine, then silence.
  Reads as: the VCN domain is power/clock-gated, and the gate is the
  firmware's job to open — which is what the DXE ladder is for.
- Re-verification of modes 1/2 on the 1.3 bore-vcn build is pending; the
  interface is identical, the runs are not yet done.

## Install from the release

Arch/CachyOS (pacman packages):

```sh
sudo pacman -U linux-cachyos-bore-vcn-bc250-7.2.6-1.3-x86_64.pkg.tar.zst \
               linux-cachyos-bore-vcn-bc250-headers-7.2.6-1.3-x86_64.pkg.tar.zst
```

Any distro (raw boot files + your bootloader, adjust `rootflags=`/`root=`):

- `bore-vcn-vmlinuz-7.2.6-1.3` + `bore-vcn-initramfs-7.2.6-1.3`
- `bc250-vmlinuz-7.2.6-1.206` + `bc250-initramfs-7.2.6-1.206`

Mode cmdlines: `kernels/modes/mode{0,1,2}.cmdline`. Verify everything with
the release `SHA256SUMS`.

## Provenance

- Base: [MastaG/linux-cachyos-bc250](https://github.com/MastaG/linux-cachyos-bc250).
- Local delta in `kernels/patches/` (40 CU unlock by duggasco, VCN
  direct-load flag).
- Gap, stated plainly: the 1.3 PKGBUILD and the `bc250_vcn_mode` patch
  source are missing (see `kernels/README.md`).
