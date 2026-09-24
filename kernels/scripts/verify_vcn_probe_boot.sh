#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_MODE=${1:?usage: verify_vcn_probe_boot.sh MODE OUTPUT}
OUTPUT=${2:-/tmp/vcn-probe-mode${EXPECTED_MODE}.out}
EXPECTED_RELEASE=7.2.0-1.91-cachyos-vcn-bc250

case "$EXPECTED_MODE" in
  0|1) ;;
  *) echo "expected mode 0 or 1" >&2; exit 1 ;;
esac

exec > >(tee "$OUTPUT") 2>&1

echo "=== VCN PROBE BOOT EVIDENCE ==="
echo "timestamp=$(date --iso-8601=seconds)"
echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
echo "expected_mode=$EXPECTED_MODE"
echo "expected_release=$EXPECTED_RELEASE"
echo

echo "=== KERNEL ==="
uname -a
cat /proc/cmdline
[[ $(uname -r) == "$EXPECTED_RELEASE" ]] \
  || { echo "FAIL: unexpected kernel release"; exit 1; }
grep -qw "amdgpu.bc250_vcn_mode=$EXPECTED_MODE" /proc/cmdline \
  || { echo "FAIL: expected mode missing from cmdline"; exit 1; }
if grep -qE '(^| )amdgpu\.fw_load_type=' /proc/cmdline; then
  echo "FAIL: global fw_load_type is forbidden"
  exit 1
fi

echo

echo "=== MODULE ==="
modinfo amdgpu | grep -E '^(filename|firmware:.*navi10_vcn|srcversion|vermagic|parm:.*bc250_vcn_mode)'
PARAMETER=/sys/module/amdgpu/parameters/bc250_vcn_mode
[[ -r "$PARAMETER" ]] || { echo "FAIL: missing bc250_vcn_mode sysfs parameter"; exit 1; }
ACTUAL_MODE=$(cat "$PARAMETER")
echo "bc250_vcn_mode=$ACTUAL_MODE"
[[ "$ACTUAL_MODE" == "$EXPECTED_MODE" ]] \
  || { echo "FAIL: module parameter mismatch"; exit 1; }

echo

echo "=== GPU AND DRM ==="
lspci -nnk -s 01:00.0
ls -l /dev/dri
[[ -e /dev/dri/card1 && -e /dev/dri/renderD128 ]] \
  || { echo "FAIL: expected DRM nodes missing"; exit 1; }
for node in card1 renderD128; do
  device=$(basename "$(readlink -f "/sys/class/drm/$node/device")")
  driver=$(basename "$(readlink -f "/sys/class/drm/$node/device/driver")")
  echo "$node device=$device driver=$driver"
  [[ "$device" == 0000:01:00.0 && "$driver" == amdgpu ]] \
    || { echo "FAIL: $node is not owned by BC-250 amdgpu"; exit 1; }
done

echo
KERNEL_LOG=$(mktemp /tmp/vcn-probe-kernel-log.XXXXXX)
trap 'rm -f "$KERNEL_LOG"' EXIT
sudo journalctl -b -k --no-pager >"$KERNEL_LOG" \
  || { echo "FAIL: cannot read current-boot kernel log"; exit 1; }

echo "=== AMDGPU BOOT LOG ==="
grep -iE 'amdgpu|bc250|vcn|uvd|jpeg|ring|KCQ|KIQ|firmware' "$KERNEL_LOG" \
  | tail -400 || true

echo

echo "=== FATAL CHECK ==="
if grep -iE 'ring kiq_[^ ]* test failed|KCQ enable failed|hw_init of IP block <gfx_v10_0> failed|amdgpu.*(GPU reset|timeout|BUG:|kernel panic)' "$KERNEL_LOG"; then
  echo "FAIL: fatal AMDGPU error detected"
  exit 1
fi

if ((EXPECTED_MODE == 0)); then
  if grep -iE 'ring (vcn|jpeg)[^ ]*|ring_(vcn|jpeg)|<(vcn|jpeg)[^>]*>.*ring' "$KERNEL_LOG"; then
    echo "FAIL: mode 0 exposed VCN/JPEG ring activity"
    exit 1
  fi
fi

if ((EXPECTED_MODE == 1)); then
  if grep -iE 'ring (vcn|jpeg)[^ ]*.*test|ring_(vcn|jpeg).*test|<(vcn|jpeg)[^>]*>.*ring.*test' "$KERNEL_LOG"; then
    echo "FAIL: mode 1 executed a forbidden VCN/JPEG ring test"
    exit 1
  fi
fi

echo
sha256sum "$OUTPUT" 2>/dev/null || true
echo "VCN_PROBE_BOOT_PASS mode=$EXPECTED_MODE release=$EXPECTED_RELEASE"
