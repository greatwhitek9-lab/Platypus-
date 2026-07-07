#!/usr/bin/env bash
set -euo pipefail

# Platypus one-shot installer
# Target: Heltec T114 / HT-n5262 nRF52840 UF2 board
# Purpose: Build or flash Zephyr Bluetooth HCI USB firmware as a BlueZ-compatible USB HCI adapter.

APP_NAME="Platypus"
BOARD_NAME="HT-n5262"
BOARD_TARGET="heltec_t114_v2/nrf52840/uf2"
UF2_FAMILY="0x239a0071"
FLASH_OFFSET="0x1000"
FLASH_SIZE="0xdf000"
USB_ID_BOOTLOADER="239a:0071"
USB_ID_APP="2fe3:000b"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEPHYR_BASE="${ZEPHYR_BASE:-$HOME/ble-dongle-build/zephyrproject/zephyr}"
WEST="${WEST:-$HOME/ble-dongle-build/.venv/bin/west}"
APP_DIR="${APP_DIR:-$REPO_ROOT/firmware/platypus-hci-usb}"
BUILD_DIR="${BUILD_DIR:-$REPO_ROOT/build/platypus-hci-usb-offset1000-nodt}"
RELEASE_DIR="${RELEASE_DIR:-$REPO_ROOT/releases}"
RELEASE_UF2="${RELEASE_UF2:-$RELEASE_DIR/platypus-hci-usb-HT-n5262-offset1000.uf2}"
MOUNT_DIR="${MOUNT_DIR:-/mnt/t114}"

ASSUME_YES=0
SKIP_BUILD=0
FLASH_ONLY=0
NO_FLASH=0
NO_VERIFY=0
INSTALL_DEPS=0

usage() {
    cat <<EOF
$APP_NAME one-shot installer

Usage:
  ./install.sh [options]

Options:
  --yes              Assume yes for prompts where possible
  --install-deps     Install common Debian/Kali dependencies with apt
  --skip-build       Do not build; flash the existing release UF2
  --flash-only       Same as --skip-build, then flash
  --no-flash         Build/patch only; do not flash
  --no-verify        Skip BlueZ verification after flashing
  -h, --help         Show this help

Environment overrides:
  ZEPHYR_BASE        Path to Zephyr tree
                     Default: $HOME/ble-dongle-build/zephyrproject/zephyr

  WEST               Path to west executable
                     Default: $HOME/ble-dongle-build/.venv/bin/west

  APP_DIR            Firmware app source directory
                     Default: ./firmware/platypus-hci-usb

  BUILD_DIR          Zephyr build directory
                     Default: ./build/platypus-hci-usb-offset1000-nodt

  RELEASE_UF2        Output/input UF2 path
                     Default: ./releases/platypus-hci-usb-HT-n5262-offset1000.uf2

Examples:
  chmod +x install.sh
  ./install.sh

  ./install.sh --skip-build

  ZEPHYR_BASE=~/zephyrproject/zephyr WEST=~/zephyr-venv/bin/west ./install.sh
EOF
}

log() {
    echo "[*] $*"
}

ok() {
    echo "[+] $*"
}

warn() {
    echo "[!] $*" >&2
}

fail() {
    echo "[x] $*" >&2
    exit 1
}

confirm() {
    local prompt="$1"
    if [[ "$ASSUME_YES" -eq 1 ]]; then
        return 0
    fi
    read -r -p "$prompt [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

for arg in "$@"; do
    case "$arg" in
        --yes) ASSUME_YES=1 ;;
        --install-deps) INSTALL_DEPS=1 ;;
        --skip-build) SKIP_BUILD=1 ;;
        --flash-only) FLASH_ONLY=1; SKIP_BUILD=1 ;;
        --no-flash) NO_FLASH=1 ;;
        --no-verify) NO_VERIFY=1 ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $arg" ;;
    esac
done

banner() {
    cat <<'EOF'

============================================================
  Platypus HT-n5262 One-Shot Installer
============================================================
  Board:   Heltec T114 / HT-n5262 nRF52840
  Output:  USB Bluetooth HCI adapter for Linux BlueZ
  Fixes:   app offset 0x1000 + UF2 family 0x239a0071
============================================================
EOF
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || return 1
}

install_deps() {
    if [[ "$INSTALL_DEPS" -ne 1 ]]; then
        return 0
    fi

    if ! need_cmd apt; then
        warn "apt not found; skipping dependency install."
        return 0
    fi

    log "Installing common dependencies with apt"
    sudo apt update
    sudo apt install -y \
        git python3 python3-venv python3-pip cmake ninja-build gperf ccache \
        dfu-util device-tree-compiler wget curl xz-utils file make gcc gcc-multilib \
        g++ libsdl2-dev libmagic1 bluez usbutils util-linux
}

inspect_uf2_inline() {
    local uf2="$1"
    python3 - "$uf2" <<'PY'
import struct
import sys
from collections import Counter

path = sys.argv[1]
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30

with open(path, 'rb') as f:
    data = f.read()

addrs = []
families = []
sizes = []
flags_seen = Counter()
blocks = len(data) // 512

for i in range(blocks):
    b = data[i*512:(i+1)*512]
    if len(b) != 512:
        continue
    magic0, magic1, flags, target, payload_size, block_no, num_blocks, family = struct.unpack_from('<IIIIIIII', b, 0)
    end_magic, = struct.unpack_from('<I', b, 508)
    if magic0 != UF2_MAGIC_START0 or magic1 != UF2_MAGIC_START1 or end_magic != UF2_MAGIC_END:
        continue
    addrs.append(target)
    families.append(family)
    sizes.append(payload_size)
    flags_seen[flags] += 1

print(f'File: {path}')
print(f'Size: {len(data)} bytes')
print(f'UF2 blocks parsed: {len(addrs)} / {blocks}')
if addrs:
    print(f'Address min: 0x{min(addrs):08x}')
    print(f'Address max: 0x{max(addrs):08x}')
    print(f'Address span end approx: 0x{max(a+s for a, s in zip(addrs, sizes)):08x}')
    print(f'Payload sizes: {sorted(set(sizes))}')
    print(f'Families: {[hex(x) for x in sorted(set(families))]}')
    print(f'Flags: {[hex(x) for x in sorted(flags_seen)]}')
else:
    print('[!] No valid UF2 blocks found')
PY
}

patch_uf2_family_inline() {
    local input="$1"
    local output="$2"
    local family="$3"

    python3 - "$input" "$output" "$family" <<'PY'
import struct
import sys

inp, outp, family_arg = sys.argv[1], sys.argv[2], sys.argv[3]
new_family = int(family_arg, 0)

UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID_PRESENT = 0x00002000

with open(inp, 'rb') as f:
    data = bytearray(f.read())

if len(data) % 512 != 0:
    raise SystemExit(f'Input size is not a multiple of 512: {len(data)}')

patched = 0
seen = set()

for off in range(0, len(data), 512):
    magic0, magic1, flags, target, payload_size, block_no, num_blocks, family = struct.unpack_from('<IIIIIIII', data, off)
    end_magic, = struct.unpack_from('<I', data, off + 508)
    if magic0 != UF2_MAGIC_START0 or magic1 != UF2_MAGIC_START1 or end_magic != UF2_MAGIC_END:
        continue
    seen.add(family)
    flags |= UF2_FLAG_FAMILY_ID_PRESENT
    struct.pack_into('<I', data, off + 8, flags)
    struct.pack_into('<I', data, off + 28, new_family)
    patched += 1

with open(outp, 'wb') as f:
    f.write(data)

print(f'Input:          {inp}')
print(f'Output:         {outp}')
print(f'Blocks patched: {patched}')
print(f'Families seen:  {[hex(x) for x in sorted(seen)]}')
print(f'New family:     {hex(new_family)}')
PY
}

prepare_app_source() {
    if [[ -f "$APP_DIR/CMakeLists.txt" ]]; then
        log "Using existing app source: $APP_DIR"
        return 0
    fi

    local sample="$ZEPHYR_BASE/samples/bluetooth/hci_usb"
    [[ -d "$sample" ]] || fail "Zephyr HCI USB sample not found: $sample"

    log "Copying Zephyr hci_usb sample into firmware directory"
    mkdir -p "$(dirname "$APP_DIR")"
    rm -rf "$APP_DIR"
    cp -a "$sample" "$APP_DIR"
}

build_firmware() {
    [[ -x "$WEST" ]] || fail "west not found or not executable: $WEST"
    [[ -d "$ZEPHYR_BASE" ]] || fail "Zephyr base not found: $ZEPHYR_BASE"

    prepare_app_source
    mkdir -p "$RELEASE_DIR"

    log "Building firmware"
    echo "    Board:      $BOARD_TARGET"
    echo "    Zephyr:     $ZEPHYR_BASE"
    echo "    West:       $WEST"
    echo "    App:        $APP_DIR"
    echo "    Build dir:  $BUILD_DIR"

    cd "$ZEPHYR_BASE"
    "$WEST" build -p always \
        -b "$BOARD_TARGET" \
        "$APP_DIR" \
        -d "$BUILD_DIR" \
        -- \
        -DCONFIG_USE_DT_CODE_PARTITION=n \
        -DCONFIG_FLASH_LOAD_OFFSET="$FLASH_OFFSET" \
        -DCONFIG_FLASH_LOAD_SIZE="$FLASH_SIZE"

    local raw_uf2="$BUILD_DIR/zephyr/zephyr.uf2"
    [[ -f "$raw_uf2" ]] || fail "Build completed but UF2 not found: $raw_uf2"

    log "Raw UF2 metadata"
    inspect_uf2_inline "$raw_uf2"

    log "Patching UF2 family for $BOARD_NAME"
    patch_uf2_family_inline "$raw_uf2" "$RELEASE_UF2" "$UF2_FAMILY"

    log "Patched UF2 metadata"
    inspect_uf2_inline "$RELEASE_UF2"

    ok "Release UF2 ready: $RELEASE_UF2"
}

find_uf2_device() {
    lsblk -pnro NAME,LABEL,FSTYPE 2>/dev/null | awk '$2=="HT-n5262" && $3=="vfat" {print $1; exit}'
}

flash_firmware() {
    [[ -f "$RELEASE_UF2" ]] || fail "Release UF2 not found: $RELEASE_UF2"

    cat <<EOF

Flash step
----------
Put the Heltec T114 into UF2 bootloader mode now:

  1. Plug in the board.
  2. Double-tap RST.
  3. Wait for the HT-n5262 removable drive to appear.

EOF

    if [[ "$ASSUME_YES" -ne 1 ]]; then
        read -r -p "Press ENTER after the HT-n5262 UF2 drive appears..."
    fi

    log "Waiting for $BOARD_NAME UF2 drive"
    local dev=""
    for _ in $(seq 1 40); do
        dev="$(find_uf2_device || true)"
        [[ -n "$dev" ]] && break
        sleep 1
    done

    [[ -n "$dev" ]] || {
        warn "Could not find HT-n5262 UF2 drive. Current USB devices:"
        lsusb || true
        warn "Current block devices:"
        lsblk -o NAME,LABEL,SIZE,FSTYPE,MOUNTPOINT || true
        fail "Board not found in UF2 mode. Double-tap RST and retry."
    }

    ok "Found UF2 block device: $dev"

    local existing_mount
    existing_mount="$(lsblk -no MOUNTPOINT "$dev" | head -1 || true)"
    local target_mount="$MOUNT_DIR"
    local mounted_by_script=0

    if [[ -n "$existing_mount" ]]; then
        target_mount="$existing_mount"
        log "Using existing mount: $target_mount"
    else
        log "Mounting $dev at $target_mount"
        sudo mkdir -p "$target_mount"
        sudo mount -t vfat "$dev" "$target_mount"
        mounted_by_script=1
    fi

    log "Copying UF2 to board"
    sudo cp -v "$RELEASE_UF2" "$target_mount/"
    sync

    if [[ "$mounted_by_script" -eq 1 ]]; then
        sudo umount "$target_mount" 2>/dev/null || true
    else
        udisksctl unmount -b "$dev" 2>/dev/null || true
    fi

    ok "Flash copy complete."
    echo
    echo "Unplug the Heltec, wait 5 seconds, then plug it back in normally."
    echo "Do not double-tap RST after flashing."
}

verify_bluez() {
    cat <<EOF

Verification step
-----------------
After normal replug, Platypus should appear as a USB Bluetooth HCI device.

EOF

    if [[ "$ASSUME_YES" -ne 1 ]]; then
        read -r -p "Press ENTER after plugging the board back in normally..."
    else
        sleep 3
    fi

    sudo modprobe btusb 2>/dev/null || true
    sudo systemctl restart bluetooth 2>/dev/null || true
    sudo rfkill unblock bluetooth 2>/dev/null || true
    sleep 3

    echo
    echo "USB check:"
    lsusb | grep -Ei "$USB_ID_APP|$USB_ID_BOOTLOADER|zephyr|nordic|ht-n5262" || true

    echo
    echo "HCI devices:"
    ls /sys/class/bluetooth/ 2>/dev/null || true

    echo
    echo "BlueZ controllers:"
    bluetoothctl list 2>/dev/null || true

    echo
    if lsusb | grep -qi "$USB_ID_APP"; then
        ok "Platypus USB HCI device detected."
    else
        warn "Platypus USB HCI device was not detected by lsusb."
    fi

    if ls /sys/class/bluetooth/ 2>/dev/null | grep -q 'hci1'; then
        ok "hci1 detected. Platypus is likely ready for BlueZ."
    else
        warn "hci1 was not detected. If this host has no internal Bluetooth, Platypus may be hci0."
    fi
}

main() {
    banner
    install_deps

    if [[ "$SKIP_BUILD" -eq 1 ]]; then
        log "Skipping build and using existing UF2: $RELEASE_UF2"
        [[ -f "$RELEASE_UF2" ]] || fail "No release UF2 found. Build first or provide RELEASE_UF2=/path/file.uf2"
    else
        if [[ ! -x "$WEST" || ! -d "$ZEPHYR_BASE" ]]; then
            if [[ -f "$RELEASE_UF2" ]]; then
                warn "Zephyr workspace or west not found; using prebuilt release UF2."
                warn "Set ZEPHYR_BASE and WEST if you want to rebuild."
            else
                fail "No Zephyr build environment and no prebuilt UF2 found. Install Zephyr or add a release UF2."
            fi
        else
            build_firmware
        fi
    fi

    if [[ "$NO_FLASH" -eq 1 ]]; then
        ok "Build-only mode complete."
        exit 0
    fi

    flash_firmware

    if [[ "$NO_VERIFY" -eq 1 ]]; then
        ok "Install complete. Verification skipped."
        exit 0
    fi

    verify_bluez
    ok "Platypus one-shot installer complete."
}

main "$@"
