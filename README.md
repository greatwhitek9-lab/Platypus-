# 🦫 Platypus

**A clean USB BLE HCI firmware build for the Heltec T114 / HT-n5262 nRF52840 board.**

Platypus turns the **Heltec T114** into a plug-in USB Bluetooth Low Energy controller for Linux. After flashing, the board stops acting like a dev board and starts behaving like a dedicated **BlueZ-compatible USB HCI adapter** that can be used by standard Linux Bluetooth tools such as `bluetoothctl`, `btmgmt`, `btmon`, and BlueZ-backed applications.

It is small, weird, practical, and slightly feral — exactly like a platypus.

---

## What Platypus does

Platypus flashes the Heltec T114 / HT-n5262 board with Zephyr's Bluetooth HCI USB firmware, then applies the extra UF2 fixes needed for the HT-n5262 bootloader.

Once flashed, the board appears on the Linux host as:

```text
NordicSemiconductor Zephyr USBD BT HCI
```

On a host that already has built-in Bluetooth, you should see two HCI controllers:

```text
hci0  hci1
```

Typically:

```text
hci0 = internal Bluetooth adapter
hci1 = Platypus / Heltec T114 USB BLE HCI adapter
```

Platypus is useful when you want a removable, dedicated BLE interface for a Linux lab machine without relying on the host laptop's internal Bluetooth chipset.

---

## Target board

Platypus is built for:

| Item | Value |
|---|---|
| Board | Heltec T114 / HT-n5262 |
| MCU | Nordic nRF52840 |
| Bootloader | HT-n5262 UF2 bootloader |
| USB boot mode | Double-tap `RST` |
| Linux stack | BlueZ |
| Known host OS | Kali Linux / Debian-style Linux |
| Firmware role | USB Bluetooth HCI adapter |

The board's UF2 bootloader identifies as:

```text
Model: HT-n5262
Board-ID: HT-n5262
UF2 family: 0x239a0071
```

---

## Why this repo exists

The stock Zephyr build target for the Heltec T114 can produce a UF2 file, but the default output did not boot correctly on the tested HT-n5262 board.

The broken build looked like this:

```text
Address min: 0x00026000
Family: 0xada52840
```

The board accepted the copied UF2 file, but after a normal unplug/replug it did not enumerate as an app. It only appeared again when forced back into UF2 bootloader mode.

The working Platypus build fixes that by forcing the correct app offset and patching the UF2 family ID.

Working Platypus UF2 metadata:

```text
Address min: 0x00001000
Families: ['0x239a0071']
```

Required build fixes:

```text
CONFIG_USE_DT_CODE_PARTITION=n
CONFIG_FLASH_LOAD_OFFSET=0x1000
CONFIG_FLASH_LOAD_SIZE=0xdf000
UF2 family patched to 0x239a0071
```

That is the core of Platypus.

---

## Repository layout

```text
Platypus/
├── README.md
├── install.sh
├── scripts/
│   ├── build_platypus.sh
│   ├── flash_uf2.sh
│   ├── one_shot_install.sh
│   └── verify_bluez.sh
├── tools/
│   ├── inspect_uf2.py
│   └── patch_uf2_family.py
├── docs/
│   └── HT-n5262-UF2-fix.md
├── firmware/
│   └── README.md
└── releases/
    └── platypus-hci-usb-HT-n5262-offset1000.uf2
```

The `releases/` folder may include a prebuilt UF2. You can also rebuild it locally from your Zephyr workspace.

---

## Quick start: flash the prebuilt UF2

Use this path if the repo already contains:

```text
releases/platypus-hci-usb-HT-n5262-offset1000.uf2
```

### 1. Put the Heltec T114 into UF2 mode

Double-tap the **RST** button on the board.

The board should appear as a small removable drive labeled something like:

```text
HT-n5262
```

On Linux, confirm with:

```bash
lsusb
lsblk -o NAME,LABEL,SIZE,FSTYPE,MOUNTPOINT
```

Expected USB identity while in bootloader mode:

```text
239a:0071 Adafruit HT-n5262
```

### 2. Flash the UF2

From the repo root:

```bash
chmod +x scripts/*.sh tools/*.py install.sh
./scripts/flash_uf2.sh releases/platypus-hci-usb-HT-n5262-offset1000.uf2
```

The script waits for the `HT-n5262` UF2 drive, copies the firmware, syncs the filesystem, and unmounts the drive.

### 3. Replug normally

After flashing:

1. Unplug the board.
2. Wait about five seconds.
3. Plug it back in normally.
4. Do **not** double-tap reset this time.

If the firmware is running, the board should no longer appear as the `HT-n5262` UF2 drive. It should appear as a USB Bluetooth HCI device.

---

## One-shot installer

The easiest full flow is:

```bash
chmod +x install.sh scripts/*.sh tools/*.py
./install.sh
```

The one-shot installer will:

1. Build the Zephyr Bluetooth HCI USB firmware.
2. Force the HT-n5262 app offset to `0x1000`.
3. Patch the UF2 family to `0x239a0071`.
4. Flash the Heltec T114 UF2 drive.
5. Verify that BlueZ sees the controller.

This assumes your Zephyr workspace exists at:

```text
$HOME/ble-dongle-build/zephyrproject/zephyr
```

and your Zephyr virtual environment has `west` at:

```text
$HOME/ble-dongle-build/.venv/bin/west
```

You can override those paths:

```bash
ZEPHYR_BASE=/path/to/zephyr WEST=/path/to/west ./install.sh
```

---

## Manual build

Use this if you want to rebuild the UF2 yourself.

```bash
chmod +x scripts/*.sh tools/*.py
./scripts/build_platypus.sh
```

The build script will:

1. Locate your Zephyr workspace.
2. Use the Zephyr Bluetooth HCI USB sample.
3. Build for `heltec_t114_v2/nrf52840/uf2`.
4. Override the default flash layout.
5. Patch the UF2 family for HT-n5262.
6. Print UF2 metadata before and after patching.

Expected final output:

```text
releases/platypus-hci-usb-HT-n5262-offset1000.uf2
```

Expected final inspection:

```text
Address min: 0x00001000
Families: ['0x239a0071']
```

---

## Manual flash

Put the board into UF2 mode by double-tapping **RST**, then run:

```bash
./scripts/flash_uf2.sh
```

By default, the flasher uses:

```text
releases/platypus-hci-usb-HT-n5262-offset1000.uf2
```

You can also pass a UF2 file explicitly:

```bash
./scripts/flash_uf2.sh path/to/firmware.uf2
```

---

## Verify on Linux

After flashing and plugging the board in normally, run:

```bash
./scripts/verify_bluez.sh
```

Or verify manually:

```bash
sudo modprobe btusb
sudo systemctl restart bluetooth
sudo rfkill unblock bluetooth

lsusb
ls /sys/class/bluetooth/
bluetoothctl list
```

A successful USB listing should include something like:

```text
2fe3:000b NordicSemiconductor Zephyr USBD BT HCI
```

A successful HCI listing should show a second controller if your machine already has internal Bluetooth:

```text
hci0  hci1
```

`hci1` is usually the Platypus board.

---

## Basic use after flashing

Platypus does not run a menu, screen UI, or standalone app. It becomes a USB Bluetooth controller for the Linux host.

That means you use it from Linux through BlueZ.

Check controller info:

```bash
sudo btmgmt --index 1 info
```

Power-cycle only the Platypus controller:

```bash
sudo btmgmt --index 1 power off
sudo btmgmt --index 1 power on
sudo btmgmt --index 1 info
```

Open the BlueZ interactive shell:

```bash
bluetoothctl
```

Inside `bluetoothctl`, select the Platypus controller by its MAC address from `bluetoothctl list`:

```text
select <Platypus controller MAC>
power on
show
```

Use the board only with devices and environments you own or are explicitly authorized to test.

---

## Troubleshooting

### Board only appears after double-tapping RST

That means the board is still only reaching UF2 bootloader mode. The app is not booting.

Check the UF2:

```bash
python3 tools/inspect_uf2.py releases/platypus-hci-usb-HT-n5262-offset1000.uf2
```

Required:

```text
Address min: 0x00001000
Families: ['0x239a0071']
```

If the address starts at `0x00026000`, rebuild with the Platypus script.

### File copies but board does not boot

Likely causes:

- UF2 family is wrong.
- App offset is wrong.
- Wrong board target was used.
- The board is still in bootloader mode.

Rebuild with:

```bash
./scripts/build_platypus.sh
```

Then flash again:

```bash
./scripts/flash_uf2.sh
```

### No `hci1`

Check USB first:

```bash
lsusb
```

If you see:

```text
NordicSemiconductor Zephyr USBD BT HCI
```

but no HCI device, reload Bluetooth support:

```bash
sudo modprobe btusb
sudo systemctl restart bluetooth
sudo rfkill unblock bluetooth
```

Then check again:

```bash
ls /sys/class/bluetooth/
bluetoothctl list
```

### `west: invalid choice: build`

Run the build from inside the Zephyr workspace, or make sure your Zephyr venv is active and points to the correct `west`:

```bash
source ~/ble-dongle-build/.venv/bin/activate
cd ~/ble-dongle-build/zephyrproject/zephyr
west help | grep build
```

The Platypus build script expects:

```text
~/ble-dongle-build/.venv/bin/west
~/ble-dongle-build/zephyrproject/zephyr
```

---

## Developer notes

The important build command is effectively:

```bash
west build -p always \
  -b heltec_t114_v2/nrf52840/uf2 \
  firmware/platypus-hci-usb \
  -d build/platypus-hci-usb-offset1000-nodt \
  -- \
  -DCONFIG_USE_DT_CODE_PARTITION=n \
  -DCONFIG_FLASH_LOAD_OFFSET=0x1000 \
  -DCONFIG_FLASH_LOAD_SIZE=0xdf000
```

Then the UF2 family is patched from:

```text
0xada52840
```

to:

```text
0x239a0071
```

using:

```bash
python3 tools/patch_uf2_family.py \
  build/platypus-hci-usb-offset1000-nodt/zephyr/zephyr.uf2 \
  releases/platypus-hci-usb-HT-n5262-offset1000.uf2 \
  0x239a0071
```

---

## What Platypus is not

Platypus is not a Bluetooth attack framework, exploit pack, or autonomous radio tool.

It is a firmware/build project that makes the Heltec T114 act as a standard USB Bluetooth HCI controller. What you do with that controller is handled by the Linux host and must stay within your local laws, lab rules, and authorization scope.

---

## Safety and authorization

Use Platypus only on systems, devices, and environments you own or have clear permission to test.

This project is intended for:

- Linux Bluetooth development
- Authorized lab testing
- Hardware bring-up
- BlueZ experimentation
- Defensive research
- Reproducible firmware builds

Do not use it to interfere with, disrupt, monitor, or access devices without authorization.

---

## Credits

Platypus uses Zephyr's Bluetooth HCI USB sample as the firmware base and adds the HT-n5262-specific build and UF2 patching flow needed to make the Heltec T114 boot correctly as a BlueZ-compatible USB controller.

Built for the Urban Poacher / KoalaByte hardware lab workflow.
