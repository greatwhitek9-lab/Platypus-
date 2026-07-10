<p align="center">
  <img src="docs/images/naughty-platypus-banner.jpg" alt="Naughty Platypus" width="100%">
</p>

<h1 align="center">Naughty Platypus</h1>

<p align="center">
  <strong>An Ubertooth-inspired Bluetooth Low Energy survey platform for the Heltec T114 / HT-n5262.</strong>
</p>

<p align="center">
  Optional TFT boot splash · Active/passive scanning · JSON streaming · Kali/Parrot host console · CSV/SQLite/GPS
</p>

> [!IMPORTANT]
> Naughty Platypus is intended for authorized BLE discovery, asset inventory, troubleshooting, education, and defensive laboratory research. It does not implement jamming, forced disconnects, packet injection, key recovery, credential attacks, or denial-of-service functionality.

---

## What is Naughty Platypus?

Naughty Platypus is the dedicated BLE-survey branch of the Platypus project. It turns the **Heltec T114 / HT-n5262 nRF52840** into a USB-connected BLE discovery sensor running Zephyr RTOS.

The firmware performs scanning on the board and streams newline-delimited JSON over USB CDC serial. The accompanying Kali/Parrot host application adds:

- Per-device caching and duplicate suppression
- Strongest-device and recently-seen views
- Advertising interval estimation
- Manufacturer ID lookup
- iBeacon, Eddystone, AltBeacon, and Fast Pair parsing
- JSONL, inventory CSV, observation CSV, and SQLite export
- Interactive curses terminal UI
- GPSD or static-coordinate tagging
- Database-backed survey sessions
- Optional advertising-channel counters when a controller event exposes a channel index
- Optional 135×240 Naughty Platypus boot splash for the Heltec ST7789V TFT

---

## Platypus vs. Naughty Platypus

| Capability | Regular Platypus | Naughty Platypus |
|---|---|---|
| Primary role | Linux USB BLE HCI adapter | Standalone BLE survey sensor |
| Linux interface | BlueZ HCI controller such as `hci1` | USB CDC serial such as `/dev/ttyACM0` |
| Main control plane | BlueZ on Linux | Firmware commands plus host console |
| Typical tools | `bluetoothctl`, `btmgmt`, `btmon` | `naughty_platypus_host.py`, serial terminal |
| Active scan default | Host controlled | Yes |
| Passive scan option | Host controlled | Yes |
| Firmware JSON stream | No | Yes |
| Host device cache | BlueZ/application dependent | Included |
| Beacon protocol parsing | External tools | Included |
| CSV/SQLite/GPS sessions | External tools | Included |
| Full Ubertooth raw-radio replacement | No | No |

Choose **regular Platypus** when you want the Heltec to appear as a normal BlueZ controller.

Choose **Naughty Platypus** when you want a dedicated BLE observation sensor with structured output and survey-session tooling.

---

## Supported hardware

| Item | Value |
|---|---|
| Board | Heltec T114 / HT-n5262 |
| MCU | Nordic nRF52840 |
| RTOS | Zephyr |
| Runtime USB interface | CDC ACM serial |
| Typical runtime device | `/dev/ttyACM0` |
| UF2 bootloader label | `HT-n5262` |
| Build target | `heltec_t114_v2/nrf52840/uf2` |
| Application offset | `0x1000` |
| Application size | `0xdf000` |
| UF2 family | `0x239a0071` |
| Tested hosts | Kali Linux, Parrot OS, Debian-derived Linux |

Expected release artifact:

```text
releases/naughty-platypus-HT-n5262-offset1000.uf2
```

---

## Optional Heltec TFT boot splash

When `CONFIG_NP_BOOT_SPLASH=y`, the firmware draws the Naughty Platypus artwork on the optional **1.14-inch ST7789V 135×240 TFT** during every normal boot. The image remains visible while BLE scanning and USB serial operation continue.

The splash implementation is deliberately non-fatal:

- It checks for the Zephyr `zephyr,display` device before drawing.
- It validates the expected 135×240 RGB565 display geometry.
- Display, SPI, power, backlight, or draw failures are reported as JSON and ignored.
- BLE scanning, commands, logging, and the Kali/Parrot host console continue when no screen is fitted.
- The TFT power rail is enabled before the Zephyr display driver initializes, while the backlight stays off until the frame is complete.
- The attached artwork is converted to a 135×240, 256-color indexed asset stored in `boot_splash_data_00.inc` through `boot_splash_data_07.inc`.
- A small eight-row working buffer is used instead of allocating a full framebuffer.

A physically absent display cannot provide positive detection because the board's SPI display bus is write-only. In that case, attempted writes are harmless and the rest of the firmware continues normally.

To redraw the splash from the serial shell:

```text
splash
```

Disable it at build time by changing:

```text
CONFIG_NP_BOOT_SPLASH=n
```

The display-ready firmware marker is:

```json
{"type":"firmware_marker","build":"ble_active_splash_v6"}
```

Successful draw output:

```json
{"type":"display_status","boot_splash":"shown","width":135,"height":240}
```

---

## Architecture

```text
Nearby BLE advertisements and scan responses
                    │
                    ▼
             nRF52840 radio
                    │
                    ▼
          Zephyr BLE scan callback
          small bounded record only
                    │
                    ▼
             Message queue
                    │
                    ▼
       Firmware advertisement parser
                    │
                    ▼
        JSONL over USB CDC serial
                    │
                    ▼
       Kali / Parrot host collector
         ├─ device cache
         ├─ duplicate suppression
         ├─ interval estimation
         ├─ beacon decoders
         ├─ manufacturer lookup
         ├─ TUI
         ├─ CSV / JSONL
         ├─ SQLite sessions
         └─ GPS tagging
```

The Bluetooth callback remains deliberately lightweight. Expensive parsing, caching, export, database operations, and terminal rendering run on the Linux host.

---

# Kali Linux and Parrot OS setup

## 1. Install dependencies

```bash
sudo apt update
sudo apt install -y \
  git python3 python3-venv python3-pip \
  cmake ninja-build gperf ccache \
  device-tree-compiler wget curl xz-utils file \
  make gcc g++ usbutils util-linux screen minicom \
  gpsd gpsd-clients
```

Clone the branch:

```bash
git clone --branch naughty-platypus --single-branch \
  https://github.com/greatwhitek9-lab/Platypus.git

cd Platypus
```

For an existing clone:

```bash
cd ~/Desktop/Platypus
git fetch origin
git switch naughty-platypus
git pull --rebase origin naughty-platypus
```

## 2. Set up the host Python environment

```bash
cd ~/Desktop/Platypus
python3 -m venv .venv-naughty
source .venv-naughty/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r tools/requirements-naughty-platypus.txt
```

## 3. Fix serial permissions

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in before relying on the new group membership.

---

# Build and flash

The project expects:

```text
ZEPHYR_BASE=$HOME/ble-dongle-build/zephyrproject/zephyr
WEST=$HOME/ble-dongle-build/.venv/bin/west
```

Make scripts executable:

```bash
chmod +x scripts/*.sh tools/*.py install_naughty_platypus.sh
```

Build:

```bash
cd ~/Desktop/Platypus
rm -rf build/naughty-platypus-offset1000
./scripts/build_naughty_platypus.sh 2>&1 | tee /tmp/naughty_build.log
```

Flash:

```bash
./scripts/flash_naughty_platypus.sh
```

When prompted:

1. Double-tap `RST`.
2. Wait for the drive labeled `HT-n5262`.
3. Let the script copy and sync the UF2.
4. Unplug the board.
5. Wait about five seconds.
6. Reconnect normally without double-tapping reset.

One-line build and flash:

```bash
cd ~/Desktop/Platypus && rm -rf build/naughty-platypus-offset1000 && ./scripts/build_naughty_platypus.sh 2>&1 | tee /tmp/naughty_build.log && ./scripts/flash_naughty_platypus.sh
```

Show useful build errors:

```bash
grep -n -i "error:\|warning:\|undefined symbol\|failed" /tmp/naughty_build.log | tail -120
```

---

# Firmware commands

Open an interactive serial terminal:

```bash
screen /dev/ttyACM0 115200
```

Type one command per line:

| Command | Action |
|---|---|
| `version` | Show firmware build |
| `status` | Show scan and queue counters |
| `survey` | Drain queued summaries and print status |
| `scan` | Start scanning |
| `stop` | Stop scanning |
| `active` | Use active scan mode |
| `passive` | Use passive scan mode |
| `mode` | Show active/passive mode |
| `reset` | Reset counters and queue |
| `commands` | List commands |
| `splash` | Redraw the optional TFT boot splash |

Active scanning is the default. Active scanning can receive scan-response data and therefore discovers more local names. Some devices will still show an empty name because they do not advertise one.

Exit `screen` with `Ctrl-A`, then `K`, then `Y`.

---

# Advanced host survey console

Activate the virtual environment:

```bash
cd ~/Desktop/Platypus
source .venv-naughty/bin/activate
```

## Interactive TUI

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --tui
```

TUI keys:

```text
q / Esc   quit
s         start scan
x         stop scan
a         active mode
p         passive mode
r         reset firmware counters
v         toggle strongest/recent sorting
d         request firmware device summaries when supported
t         request firmware strongest summaries when supported
c         show advertising-channel capability/counts
```

## Full survey session with all exports

```bash
mkdir -p captures

python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --tui \
  --jsonl captures/session.jsonl \
  --events-csv captures/observations.csv \
  --csv captures/devices.csv \
  --db captures/surveys.sqlite \
  --session-name "Office BLE survey"
```

Outputs:

| Output | Purpose |
|---|---|
| JSONL | Normalized raw event stream |
| Observation CSV | One row per retained advertisement |
| Inventory CSV | One row per cached device |
| SQLite | Sessions, observations, and final device inventory |

## Timed survey

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --duration 300 \
  --csv captures/devices.csv \
  --events-csv captures/observations.csv
```

## Strongest or recently-seen summaries

Strongest-first:

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --sort strongest
```

Recently-seen first:

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --sort recent
```

In the TUI, press `v` to switch between the two views.

---

# Per-device cache and duplicate suppression

The host maintains one record per reported BLE address and tracks:

- First and last seen timestamps
- Observation count
- Retained and suppressed counts
- Last, strongest, weakest, and average RSSI
- Estimated advertising interval
- Latest local name
- Manufacturer identifier/name
- Beacon type and identifier
- Last manufacturer/service/payload data
- Last GPS fix

Host duplicate suppression defaults to a 1.5-second window:

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --dedupe-window 1.5
```

Disable host duplicate suppression:

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --dedupe-window 0
```

Duplicate suppression is an analysis/output control. The device observation counter still records received events.

---

# Advertising interval estimation

The host estimates the interval between observations for each address using an exponential moving average.

The estimate is useful for survey comparison and identifying periodic advertisers, but it is not guaranteed to equal the configured BLE advertising interval because:

- Advertisers add randomized delay.
- Individual packets may be missed.
- Scan windows may not cover every advertising event.
- Active scan responses can add observations.
- Randomized addresses can split one physical device into multiple cache entries.

The value is exported as:

```text
interval_ema_ms
```

---

# Advertising-channel statistics

The host accepts a `channel` or `primary_channel` field when a firmware/controller API exposes it and counts observations per channel.

The current Zephyr scan callback used by this HT-n5262 build does **not reliably expose the exact BLE advertising channel index**, so the TUI normally reports:

```text
BLE advertising channels: not exposed by current controller callback
```

This is a capability limitation, not a guessed statistic. Future firmware/controller backends can add the field without changing the host export format.

---

# Manufacturer lookup

A built-in table covers several common Bluetooth company identifiers. Supply a larger Bluetooth SIG-style CSV with:

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --manufacturer-db /path/to/company_identifiers.csv
```

The CSV parser accepts common ID columns such as:

```text
Decimal
Value
Company Identifier
company_id
ID
Hex
```

and name columns such as:

```text
Company
Company Name
Organization
Name
```

Manufacturer identifiers are decoded from the first two manufacturer-data bytes using Bluetooth little-endian ordering.

---

# Beacon and service parsing

The host recognizes:

| Protocol | Source data |
|---|---|
| iBeacon | Apple manufacturer data (`0x004C`, type `0x0215`) |
| AltBeacon | Manufacturer data with beacon code `0xBEAC` |
| Eddystone UID | Service UUID `0xFEAA`, frame `0x00` |
| Eddystone URL | Service UUID `0xFEAA`, frame `0x10` |
| Eddystone TLM | Service UUID `0xFEAA`, frame `0x20` |
| Eddystone EID | Service UUID `0xFEAA`, frame `0x30` |
| Fast Pair | Service UUID `0xFE2C` |

Decoded fields are written to:

```text
beacon_type
beacon_id
beacon_details
```

The parser only interprets data that was openly advertised. It does not connect to devices or request protected information.

---

# GPS tagging

## GPSD

Start GPSD for your receiver, then run:

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --gpsd 127.0.0.1:2947 \
  --db captures/mobile-survey.sqlite \
  --events-csv captures/mobile-observations.csv \
  --tui
```

Check GPSD separately:

```bash
gpspipe -w
```

## Static coordinates

```bash
python3 tools/naughty_platypus_host.py \
  --port /dev/ttyACM0 \
  --lat 40.7128 \
  --lon -74.0060 \
  --alt 15 \
  --db captures/fixed-site.sqlite
```

GPS fields are attached to retained observations and final device records.

---

# SQLite session database

The database contains:

```text
sessions
observations
devices
```

Inspect it:

```bash
sqlite3 captures/surveys.sqlite
```

Example queries:

```sql
SELECT id, name, datetime(started_at, 'unixepoch'), port
FROM sessions
ORDER BY id DESC;

SELECT addr, name, manufacturer_name, beacon_type, best_rssi, count
FROM devices
WHERE session_id = 1
ORDER BY best_rssi DESC;

SELECT datetime(seen_at, 'unixepoch'), addr, rssi, latitude, longitude
FROM observations
WHERE session_id = 1
ORDER BY seen_at;
```

---

# Example firmware output

```json
{"type":"adv_summary","addr":"B8:27:EB:E8:70:0A (public)","name":"KB-BLE-TEST","rssi":-67,"adv_type":0,"data_len":18,"mfg":"","svc16":"0f18","drained_events":42}
{"type":"survey_status","scanning":true,"scan_mode":"active","adv_events":828,"named_events":4,"mfg_events":30,"svc_events":12,"strongest_rssi":-61,"weakest_rssi":-95}
{"type":"queue_status","queued_events":828,"dropped_events":0,"drained_events":828,"pending":0}
```

Randomized BLE addresses should not be treated as permanent physical-device identifiers.

---

# Run decoder tests

```bash
python3 -m unittest tests/test_np_protocols.py
```

---

# Troubleshooting

## No `/dev/ttyACM0`

```bash
lsusb
ls -l /dev/ttyACM*
lsblk -o NAME,LABEL,SIZE,FSTYPE,MOUNTPOINT
sudo dmesg --follow
```

If the board shows as the `HT-n5262` removable drive, it is still in UF2 bootloader mode. Reconnect it normally.

## Permission denied

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in.

## Serial device busy

```bash
sudo lsof /dev/ttyACM0
sudo fuser -v /dev/ttyACM0
```

Close other `screen`, `minicom`, `cat`, or ModemManager sessions.

## ModemManager interference

```bash
sudo systemctl stop ModemManager 2>/dev/null || true
```

## Names are blank

Use active mode:

```text
active
mode
```

Blank names remain normal for advertisers that omit the Local Name field.

## Queue drops

```text
status
```

If `dropped_events` rises rapidly, reduce serial output, use passive mode in dense environments, or rely on host-side caching and deduplication rather than printing every raw record indefinitely.

---

# Repository layout

```text
Platypus/
├── README.md
├── firmware/naughty-platypus/
│   └── src/
│       ├── boot_splash.c
│       ├── boot_splash.h
│       ├── boot_splash_image.c
│       ├── boot_splash_image.h
│       └── boot_splash_data_00.inc ... boot_splash_data_07.inc
├── scripts/
├── tools/
│   ├── naughty_platypus_host.py
│   ├── np_protocols.py
│   └── requirements-naughty-platypus.txt
├── tests/
│   └── test_np_protocols.py
├── docs/images/
└── releases/
```

---

# Responsible use

Use Naughty Platypus only:

- On equipment and networks you own
- In environments where you have explicit authorization
- For defensive discovery, inventory, troubleshooting, education, and research
- In compliance with applicable privacy, radio, and computer-access laws

---

# Credits

- Zephyr Project
- Nordic Semiconductor
- Heltec Automation
- BlueZ
- GreatWhiteK9 Lab
- Urban Poacher

---

## Branch

This README describes:

```text
naughty-platypus
```

For a normal BlueZ HCI controller, switch back to the regular Platypus branch and follow that branch's README.
