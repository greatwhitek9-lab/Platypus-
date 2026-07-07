# Naughty Platypus

Experimental branch for a Heltec T114 / HT-n5262 nRF52840 BLE capture build that feels closer to an Ubertooth-style workflow while staying focused on passive, authorized lab use.

## Goal

Naughty Platypus is not meant to replace the stable Platypus USB HCI adapter build. The stable build makes the T114 appear to Linux as a BlueZ-compatible USB Bluetooth controller. Naughty Platypus is a separate firmware role that makes the board behave more like a USB-connected BLE capture instrument.

The first target is simple and useful:

```text
Heltec T114 -> USB CDC serial -> Kali host script -> JSONL/CSV capture logs -> Wireshark/Kismet bridge later
```

## Scope for this branch

Allowed in this branch:

- Passive BLE advertisement observation
- Timestamped BLE advertisement metadata capture
- RSSI/channel/address/type logging for owned or authorized lab environments
- JSONL and CSV capture output
- Future Wireshark/Kismet export bridge
- Defensive anomaly detection, such as advertisement floods, suspicious device churn, or unusually high signal/device density

Not implemented in this branch:

- Jamming
- Deauthentication or disruption features
- Unauthorized packet injection
- Unauthorized GATT writes
- Credential/key cracking automation
- Tools intended to interfere with devices outside an owned lab

## Firmware modes

The repo should eventually support two clean firmware personalities:

| Mode | USB identity | Host stack | Purpose |
|---|---|---|---|
| Platypus HCI | USB BT HCI | BlueZ | Normal Linux BLE adapter |
| Naughty Platypus | USB CDC serial | Host capture script | Passive BLE capture/logging |

## Phase 1 command model

The first firmware can be very small. It may begin scanning automatically and stream JSON lines, or later expose a compact command interface:

```text
NPING
NINFO
NSCAN ON
NSCAN OFF
NSTATS
NRESET
```

Suggested line-oriented responses:

```json
{"event":"ready","name":"naughty-platypus","mode":"passive-ble-observer"}
{"event":"adv","ms":12345,"addr":"AA:BB:CC:DD:EE:FF","type":0,"rssi":-61,"len":29}
{"event":"stats","adv_seen":421,"scan_errors":0}
```

## Capture schema

Minimum advertisement event fields:

| Field | Meaning |
|---|---|
| `event` | `adv`, `ready`, `stats`, or `error` |
| `ms` | Device uptime in milliseconds |
| `addr` | BLE advertiser address as seen by the receiver |
| `type` | BLE advertisement report type |
| `rssi` | Received signal strength in dBm |
| `len` | Advertisement payload length |

Optional future fields:

- `addr_type`
- `name`
- `manufacturer_id`
- `service_uuids`
- `channel`
- `phy`
- `payload_hex`, disabled by default unless explicitly requested for a closed lab capture

## Kali host workflow

Flash the Naughty Platypus UF2, plug the T114 back in normally, then run:

```bash
python3 tools/naughty_platypus_host.py --port /dev/ttyACM0 --jsonl captures/naughty.jsonl --csv captures/naughty.csv
```

For privacy-conscious demos:

```bash
python3 tools/naughty_platypus_host.py --port /dev/ttyACM0 --redact-addresses
```

## Roadmap

1. Add passive advertisement scan firmware.
2. Add host-side JSONL/CSV logger.
3. Add PCAPNG or extcap bridge for Wireshark.
4. Add Kismet datasource helper.
5. Add lab-only selected-connection following research notes without disruptive behavior.
6. Add KoalaByte Blue menu integration.

## Build target

Use the same HT-n5262 bootloader requirements as the main Platypus build:

```text
Board: heltec_t114_v2/nrf52840/uf2
Flash offset: 0x1000
UF2 family: 0x239a0071
```

The first build script is `scripts/build_naughty_platypus.sh`.
