#!/usr/bin/env bash
set -Eeuo pipefail

if ((EUID != 0)); then
  echo "run as root" >&2
  exit 1
fi

PACKAGE_DIR=${1:-/tmp/bc250-vcn-probe-packages}
KERNEL_PACKAGE=linux-cachyos-vcn-bc250
HEADERS_PACKAGE=linux-cachyos-vcn-bc250-headers
VERSION=7.2.0-1.91
RELEASE=7.2.0-1.91-cachyos-vcn-bc250
KERNEL_ARCHIVE="$PACKAGE_DIR/${KERNEL_PACKAGE}-${VERSION}-x86_64.pkg.tar.zst"
HEADERS_ARCHIVE="$PACKAGE_DIR/${HEADERS_PACKAGE}-${VERSION}-x86_64.pkg.tar.zst"
KERNEL_SHA256=5b25de8645e94b026d90dc650301ca027f61140f1fd5d835549d9c8117504832
HEADERS_SHA256=fc4d6890f1e289934f229167a9db58a98900189aca10c0287b97887118c6aa12
DROPIN=/etc/limine-entry-tool.d/90-bc250-vcn-probe.conf
STATE_DIR=/var/lib/bc250-vcn-probe
BASE='quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=14fe5cec-acf0-4986-8103-251a5706bbac video=DP-1:1920x1080@60 amdgpu.sg_display=0 ttm.pages_limit=1048576 systemd.zram=0 loglevel=0 mitigations=off acpi_enforce_resources=lax'
MODE0_NAME=${KERNEL_PACKAGE}-mode0
MODE1_NAME=${KERNEL_PACKAGE}-mode1
MODE0_CMDLINE="$BASE amdgpu.bc250_vcn_mode=0"
MODE1_CMDLINE="$BASE amdgpu.bc250_vcn_mode=1"

fail() {
  printf 'VCN probe install failure: %s\n' "$*" >&2
  exit 1
}

require_hash() {
  local path=$1 expected=$2 actual
  [[ -f "$path" ]] || fail "missing package: $path"
  actual=$(sha256sum "$path" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || fail "hash mismatch for $path: $actual"
}

sync_limine_config() {
  local destination mountpoint
  local -a destinations=(/boot/EFI/limine/limine.conf)

  while read -r mountpoint; do
    [[ -n "$mountpoint" ]] || continue
    destinations+=("$mountpoint/limine.conf" "$mountpoint/EFI/limine/limine.conf")
  done < <(findmnt -rn -o TARGET,LABEL | awk '$2 == "BC250VCN" { print $1 }')

  destinations+=(
    /run/media/steammachine/BC250VCN/limine.conf
    /run/media/steammachine/BC250VCN/EFI/limine/limine.conf
    /mnt/BC250VCN/limine.conf
    /mnt/BC250VCN/EFI/limine/limine.conf
  )

  for destination in "${destinations[@]}"; do
    if [[ -f "$destination" ]]; then
      install -m 0644 /boot/limine.conf "$destination"
    fi
  done
}

if grep -qE '(^| )amdgpu\.(bc250_vcn|bc250_vcn_mode|fw_load_type)=' /proc/cmdline; then
  fail "refusing installation from an experimental AMDGPU boot"
fi

[[ $(uname -r) == 7.2.0-1.1-cachyos-bc250 ]] \
  || fail "expected stock running kernel, found $(uname -r)"

require_hash "$KERNEL_ARCHIVE" "$KERNEL_SHA256"
require_hash "$HEADERS_ARCHIVE" "$HEADERS_SHA256"

for package in "$KERNEL_PACKAGE" "$HEADERS_PACKAGE"; do
  if pacman -Q "$package" >/dev/null 2>&1; then
    installed_version=$(pacman -Q "$package" | awk '{print $2}')
    [[ "$installed_version" == "$VERSION" ]] \
      || fail "unexpected preinstalled $package version: $installed_version"
  fi
done

install -d -m 0755 "$STATE_DIR" "$(dirname "$DROPIN")"
if [[ ! -f "$STATE_DIR/limine.conf.before-install" ]]; then
  cp -a /boot/limine.conf "$STATE_DIR/limine.conf.before-install"
fi
if [[ -f "$DROPIN" && ! -f "$STATE_DIR/90-bc250-vcn-probe.conf.before-install" ]]; then
  cp -a "$DROPIN" "$STATE_DIR/90-bc250-vcn-probe.conf.before-install"
fi

cat >"$DROPIN" <<EOF
KERNEL_CMDLINE[$KERNEL_PACKAGE]+="$MODE0_CMDLINE"
KERNEL_CMDLINE[$MODE0_NAME]+="$MODE0_CMDLINE"
KERNEL_CMDLINE[$MODE1_NAME]+="$MODE1_CMDLINE"
EOF

if ! pacman -Q "$KERNEL_PACKAGE" "$HEADERS_PACKAGE" >/dev/null 2>&1; then
  pacman -U --noconfirm "$KERNEL_ARCHIVE" "$HEADERS_ARCHIVE"
fi

pacman -Q "$KERNEL_PACKAGE" "$HEADERS_PACKAGE"
[[ $(pacman -Q "$KERNEL_PACKAGE" | awk '{print $2}') == "$VERSION" ]] \
  || fail "unexpected installed kernel package version"
[[ $(pacman -Q "$HEADERS_PACKAGE" | awk '{print $2}') == "$VERSION" ]] \
  || fail "unexpected installed headers package version"

MACHINE_ID=$(cat /etc/machine-id)
BOOT_KERNEL_DIR="/boot/$MACHINE_ID/$KERNEL_PACKAGE"
INITRAMFS="$BOOT_KERNEL_DIR/initramfs"
VMLINUX="$BOOT_KERNEL_DIR/vmlinuz"
[[ -f "$INITRAMFS" ]] || fail "missing initramfs: $INITRAMFS"
[[ -f "$VMLINUX" ]] || fail "missing kernel image: $VMLINUX"

MODULE=/usr/lib/modules/$RELEASE/kernel/drivers/gpu/drm/amd/amdgpu/amdgpu.ko.zst
[[ -f "$MODULE" ]] || fail "missing packaged AMDGPU module: $MODULE"
module_parameters=$(modinfo -k "$RELEASE" -F parm amdgpu)
module_firmware=$(modinfo -k "$RELEASE" -F firmware amdgpu)
grep -Fq 'bc250_vcn_mode:' <<<"$module_parameters" \
  || fail "installed AMDGPU module lacks bc250_vcn_mode"
grep -Fxq 'amdgpu/navi10_vcn.bin' <<<"$module_firmware" \
  || fail "installed AMDGPU module lacks navi10_vcn.bin declaration"

limine-entry-tool --remove-kernel "$KERNEL_PACKAGE" --keep-files --quiet || true
limine-entry-tool --remove-kernel "$MODE0_NAME" --keep-files --quiet || true
limine-entry-tool --remove-kernel "$MODE1_NAME" --keep-files --quiet || true
limine-entry-tool --add-kernel "$KERNEL_PACKAGE" "$INITRAMFS" "$VMLINUX" -mode0 \
  --comment 'BC-250 VCN control: mode 0, hardware disabled'
limine-entry-tool --add-kernel "$KERNEL_PACKAGE" "$INITRAMFS" "$VMLINUX" -mode1 \
  --comment 'BC-250 VCN probe: mode 1, no hardware access'

limine-entry-tool --get-cmdline "$MODE0_NAME" | tail -n 1 | grep -Fqx "$MODE0_CMDLINE" \
  || fail "mode 0 command line mismatch"
limine-entry-tool --get-cmdline "$MODE1_NAME" | tail -n 1 | grep -Fqx "$MODE1_CMDLINE" \
  || fail "mode 1 command line mismatch"

grep -Fq "//$MODE0_NAME" /boot/limine.conf || fail "mode 0 entry missing from limine.conf"
grep -Fq "//$MODE1_NAME" /boot/limine.conf || fail "mode 1 entry missing from limine.conf"
sync_limine_config

cat >"$STATE_DIR/install-manifest.txt" <<EOF
installed_at=$(date --iso-8601=seconds)
running_kernel=$(uname -r)
release=$RELEASE
kernel_archive=$KERNEL_ARCHIVE
kernel_sha256=$KERNEL_SHA256
headers_archive=$HEADERS_ARCHIVE
headers_sha256=$HEADERS_SHA256
mode0_name=$MODE0_NAME
mode0_cmdline=$MODE0_CMDLINE
mode1_name=$MODE1_NAME
mode1_cmdline=$MODE1_CMDLINE
EOF

sha256sum "$INITRAMFS" "$VMLINUX" "$MODULE" /boot/limine.conf \
  >"$STATE_DIR/installed-files.sha256"

printf 'VCN_PROBE_INSTALL_PASS release=%s entries=%s,%s\n' \
  "$RELEASE" "$MODE0_NAME" "$MODE1_NAME"
printf 'running kernel unchanged: %s\n' "$(uname -r)"
