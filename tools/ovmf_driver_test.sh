#!/bin/sh
# ovmf_driver_test.sh — load a DXE driver .efi in UEFI Shell under QEMU/OVMF.
#
# Usage: scripts/ovmf_driver_test.sh <driver.efi> <label>
# Needs (Arch): qemu-system-x86, edk2-ovmf, edk2-shell, mtools, dosfstools.
# Out: serial log + verdict. Exit 0 iff load Success + entry 0x0 + shell alive.
#
# What it proves: the PE loads, the entry point runs and returns, the shell
# survives. It does NOT prove hardware behavior (QEMU has no BC250 SMU; a
# mailbox driver is expected to take its fail-fast timeout path here).
set -e
EFI="$1"; LABEL="$2"
[ -f "$EFI" ] || { echo "usage: $0 <driver.efi> <label>"; exit 2; }
: "${LABEL:=run}"
for t in qemu-system-x86_64 mkfs.fat mcopy mmd; do
  command -v "$t" >/dev/null 2>&1 || { echo "missing: $t"; exit 2; }
done
CODE=/usr/share/edk2-ovmf/x64/OVMF_CODE.4m.fd
VARS0=/usr/share/edk2-ovmf/x64/OVMF_VARS.4m.fd
SHELL=/usr/share/edk2-shell/x64/Shell_Full.efi
[ -f "$CODE" ] && [ -f "$VARS0" ] && [ -f "$SHELL" ] || { echo "missing edk2 files"; exit 2; }

W="${OVMF_WORK:-$HOME/.cache/ovmf-test}/$LABEL"
mkdir -p "$W"
export MTOOLS_SKIP_CHECK=1
mkfs.fat -F 32 -C "$W/disk.img" 65536 >/dev/null 2>&1
mmd -i "$W/disk.img" ::EFI ::EFI/BOOT
mcopy -i "$W/disk.img" "$SHELL" ::EFI/BOOT/BOOTX64.EFI
printf 'fs0:\r\nload driver.efi\r\necho DRIVER-LOAD-DONE lasterror=%%lasterror%%\r\necho OVMF-TEST-PHASE-DONE\r\nreset -s\r\n' > "$W/startup.nsh"
mcopy -i "$W/disk.img" "$W/startup.nsh" ::STARTUP.NSH
mcopy -i "$W/disk.img" "$EFI" ::DRIVER.EFI
cp "$VARS0" "$W/vars.fd"
S=$(date +%s)
timeout 150 qemu-system-x86_64 -M q35 -m 512 -display none \
  -serial "file:$W/serial.log" -no-reboot \
  -drive "if=pflash,format=raw,readonly=on,file=$CODE" \
  -drive "if=pflash,format=raw,file=$W/vars.fd" \
  -device ahci,id=ahci -device ide-hd,drive=disk,bus=ahci.0 \
  -drive "id=disk,file=$W/disk.img,format=raw,if=none" >/dev/null 2>&1
RC=$?
E=$(date +%s)
echo "wall=$((E - S))s qemu_rc=$RC log=$W/serial.log"
LOAD_OK=$(grep -a -c "loaded at .* - Success" "$W/serial.log" || true)
RC_OK=$(grep -a -c "DRIVER-LOAD-DONE lasterror=0x0" "$W/serial.log" || true)
DONE_OK=$(grep -a -c "OVMF-TEST-PHASE-DONE" "$W/serial.log" || true)
echo "load_success=$LOAD_OK entry_0x0=$RC_OK shell_alive=$DONE_OK"
[ "$LOAD_OK" -ge 1 ] && [ "$RC_OK" -ge 1 ] && [ "$DONE_OK" -ge 1 ] && [ "$RC" -eq 0 ]
