# Bc250VcnUnlockDxe sources

- `BC250VCNUnlockDxe.c` — route-B baseline.
- `BC250VCNUnlockDxe_secure.c` — secure-reads-only variant (v008).
- `BC250VCNUnlockDxe_rtb.c` — ReadyToBoot-deferred variant (v009).
- `.h` / `.inf` — module header and EDK2 descriptor (`DEPEX TRUE`).

Build (EDK2 `RELEASE_GCC`, X64, `-Werror` clean; result must be 12288 bytes):

```sh
export WORKSPACE=<your-edk2-ws> EDK_TOOLS_PATH=<edk2>/BaseTools \
  CONF_PATH=<edk2>/Conf PACKAGES_PATH=$WORKSPACE:<edk2> GCC_BIN=/usr/bin/
build -p Bc250VcnUnlockPkg/Bc250VcnUnlockPkg.dsc \
  -m Bc250VcnUnlockPkg/Bc250VcnUnlockDxe/Bc250VcnUnlockDxe.inf \
  -a X64 -t GCC -b RELEASE
```

Pack to FFS (PE32 section FIRST, then DEPEX — order matters, see the v003b lesson):

```sh
GenSec -s EFI_SECTION_PE32 -o sec.pe32 DRIVER.efi
GenSec -s EFI_SECTION_DXE_DEPEX -o sec.depex DRIVER.depex   # TRUE -> 06 08
GenFfs -t EFI_FV_FILETYPE_DRIVER -g b6250780-7e00-4203-900c-23443b1413fe \
  -o DRIVER.ffs -i sec.pe32 -i sec.depex
```

Validate with `tools/ovmf_driver_test.sh` before any BIOS integration.
