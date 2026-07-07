# Naughty Platypus firmware

This Zephyr application is the experimental passive BLE observer firmware for the Heltec T114 / HT-n5262 nRF52840 board.

It is intentionally separate from the main Platypus HCI firmware.

## Behavior

Current target behavior:

1. Boot as a USB CDC/console-style device.
2. Enable the Zephyr Bluetooth stack.
3. Start passive BLE scanning.
4. Print line-oriented JSON records for each BLE advertisement report.
5. Let the Kali host script collect the stream into JSONL and CSV files.

## Safety boundary

This firmware is passive. It does not transmit attack traffic, jam, disrupt, inject packets, write GATT characteristics, or attempt to bypass pairing/encryption.

## Build

From the repo root:

```bash
chmod +x scripts/build_naughty_platypus.sh
./scripts/build_naughty_platypus.sh
```

Expected output:

```text
releases/naughty-platypus-sniffer-HT-n5262-offset1000.uf2
```

## Flash

Put the board in UF2 mode by double-tapping `RST`, then flash the generated UF2:

```bash
./scripts/flash_uf2.sh releases/naughty-platypus-sniffer-HT-n5262-offset1000.uf2
```

After flashing, unplug and replug normally. The board should expose a serial device such as `/dev/ttyACM0`.

## Host capture

```bash
python3 tools/naughty_platypus_host.py --port /dev/ttyACM0 --jsonl captures/naughty.jsonl --csv captures/naughty.csv
```
