#!/usr/bin/env python3
"""Advanced Naughty Platypus host survey console for Kali and Parrot OS.

Features:
- Per-device cache and optional host-side duplicate suppression
- Strongest/recent views and advertising interval estimation
- Manufacturer lookup plus iBeacon/Eddystone/AltBeacon/Fast Pair parsing
- JSONL, observation CSV, inventory CSV, and SQLite survey sessions
- Optional GPSD or static GPS tagging
- Interactive curses terminal UI
"""

from __future__ import annotations

import argparse
import csv
import curses
import json
import signal
import socket
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, TextIO, Tuple

try:
    import serial
except ImportError:
    print("Missing dependency: pyserial", file=sys.stderr)
    print("Install with: python3 -m pip install pyserial", file=sys.stderr)
    raise

from np_protocols import beacon_json, load_company_ids, manufacturer_lookup, parse_beacon


@dataclass
class GPSFix:
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    source: str = "none"
    updated_at: float = 0.0


class GPSProvider:
    def poll(self) -> GPSFix:
        return GPSFix()

    def close(self) -> None:
        return None


class StaticGPSProvider(GPSProvider):
    def __init__(self, latitude: float, longitude: float, altitude_m: Optional[float]) -> None:
        self.fix = GPSFix(latitude, longitude, altitude_m, "static", time.time())

    def poll(self) -> GPSFix:
        return self.fix


class GPSDProvider(GPSProvider):
    """Minimal GPSD JSON client with no external Python dependency."""

    def __init__(self, endpoint: str) -> None:
        host, port = parse_host_port(endpoint, 2947)
        self.sock = socket.create_connection((host, port), timeout=3.0)
        self.sock.setblocking(False)
        self.sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
        self.buffer = ""
        self.fix = GPSFix(source="gpsd")

    def poll(self) -> GPSFix:
        while True:
            try:
                chunk = self.sock.recv(4096)
            except BlockingIOError:
                break
            except OSError:
                break
            if not chunk:
                break
            self.buffer += chunk.decode("utf-8", errors="replace")

        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("class") != "TPV":
                continue
            lat = event.get("lat")
            lon = event.get("lon")
            if lat is None or lon is None:
                continue
            self.fix = GPSFix(
                latitude=float(lat),
                longitude=float(lon),
                altitude_m=float(event["alt"]) if event.get("alt") is not None else None,
                source="gpsd",
                updated_at=time.time(),
            )
        return self.fix

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


@dataclass
class DeviceRecord:
    addr: str
    first_seen: float
    last_seen: float
    count: int = 0
    emitted_count: int = 0
    suppressed_count: int = 0
    last_rssi: int = -127
    best_rssi: int = -127
    worst_rssi: int = 127
    rssi_sum: int = 0
    name: str = ""
    adv_type: int = 0
    data_len: int = 0
    mfg_hex: str = ""
    svc16_hex: str = ""
    payload_hex: str = ""
    manufacturer_id: Optional[int] = None
    manufacturer_name: str = ""
    beacon_type: str = ""
    beacon_id: str = ""
    beacon_details: str = ""
    interval_ema_ms: float = 0.0
    interval_samples: int = 0
    last_payload_signature: str = ""
    last_payload_seen: float = 0.0
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None

    @property
    def avg_rssi(self) -> float:
        return self.rssi_sum / self.count if self.count else -127.0

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.last_seen)


class SessionDatabase:
    def __init__(self, path: str, port: str, session_name: str) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(p)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        cur = self.conn.execute(
            "INSERT INTO sessions(name, started_at, port) VALUES (?, ?, ?)",
            (session_name, time.time(), port),
        )
        self.session_id = int(cur.lastrowid)
        self.pending = 0
        self.conn.commit()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                port TEXT,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                seen_at REAL NOT NULL,
                addr TEXT NOT NULL,
                name TEXT,
                rssi INTEGER,
                adv_type INTEGER,
                data_len INTEGER,
                manufacturer_id INTEGER,
                manufacturer_name TEXT,
                beacon_type TEXT,
                beacon_id TEXT,
                mfg_hex TEXT,
                svc16_hex TEXT,
                payload_hex TEXT,
                latitude REAL,
                longitude REAL,
                altitude_m REAL
            );
            CREATE INDEX IF NOT EXISTS idx_observations_session_addr
                ON observations(session_id, addr);
            CREATE INDEX IF NOT EXISTS idx_observations_seen
                ON observations(seen_at);
            CREATE TABLE IF NOT EXISTS devices (
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                addr TEXT NOT NULL,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                count INTEGER NOT NULL,
                emitted_count INTEGER NOT NULL,
                suppressed_count INTEGER NOT NULL,
                last_rssi INTEGER,
                best_rssi INTEGER,
                worst_rssi INTEGER,
                avg_rssi REAL,
                interval_ema_ms REAL,
                name TEXT,
                manufacturer_id INTEGER,
                manufacturer_name TEXT,
                beacon_type TEXT,
                beacon_id TEXT,
                last_latitude REAL,
                last_longitude REAL,
                last_altitude_m REAL,
                PRIMARY KEY(session_id, addr)
            );
            """
        )

    def add_observation(self, rec: DeviceRecord, seen_at: float) -> None:
        self.conn.execute(
            """
            INSERT INTO observations(
                session_id, seen_at, addr, name, rssi, adv_type, data_len,
                manufacturer_id, manufacturer_name, beacon_type, beacon_id,
                mfg_hex, svc16_hex, payload_hex, latitude, longitude, altitude_m
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id, seen_at, rec.addr, rec.name, rec.last_rssi,
                rec.adv_type, rec.data_len, rec.manufacturer_id,
                rec.manufacturer_name, rec.beacon_type, rec.beacon_id,
                rec.mfg_hex, rec.svc16_hex, rec.payload_hex,
                rec.latitude, rec.longitude, rec.altitude_m,
            ),
        )
        self.pending += 1
        if self.pending >= 50:
            self.conn.commit()
            self.pending = 0

    def finalize(self, records: Dict[str, DeviceRecord]) -> None:
        for rec in records.values():
            self.conn.execute(
                """
                INSERT INTO devices(
                    session_id, addr, first_seen, last_seen, count, emitted_count,
                    suppressed_count, last_rssi, best_rssi, worst_rssi, avg_rssi,
                    interval_ema_ms, name, manufacturer_id, manufacturer_name,
                    beacon_type, beacon_id, last_latitude, last_longitude,
                    last_altitude_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, addr) DO UPDATE SET
                    first_seen=excluded.first_seen,
                    last_seen=excluded.last_seen,
                    count=excluded.count,
                    emitted_count=excluded.emitted_count,
                    suppressed_count=excluded.suppressed_count,
                    last_rssi=excluded.last_rssi,
                    best_rssi=excluded.best_rssi,
                    worst_rssi=excluded.worst_rssi,
                    avg_rssi=excluded.avg_rssi,
                    interval_ema_ms=excluded.interval_ema_ms,
                    name=excluded.name,
                    manufacturer_id=excluded.manufacturer_id,
                    manufacturer_name=excluded.manufacturer_name,
                    beacon_type=excluded.beacon_type,
                    beacon_id=excluded.beacon_id,
                    last_latitude=excluded.last_latitude,
                    last_longitude=excluded.last_longitude,
                    last_altitude_m=excluded.last_altitude_m
                """,
                (
                    self.session_id, rec.addr, rec.first_seen, rec.last_seen,
                    rec.count, rec.emitted_count, rec.suppressed_count,
                    rec.last_rssi, rec.best_rssi, rec.worst_rssi, rec.avg_rssi,
                    rec.interval_ema_ms, rec.name, rec.manufacturer_id,
                    rec.manufacturer_name, rec.beacon_type, rec.beacon_id,
                    rec.latitude, rec.longitude, rec.altitude_m,
                ),
            )
        self.conn.execute(
            "UPDATE sessions SET ended_at=? WHERE id=?",
            (time.time(), self.session_id),
        )
        self.conn.commit()
        self.conn.close()


class EventCSV:
    FIELDS = [
        "seen_at_epoch", "addr", "name", "rssi", "adv_type", "data_len",
        "manufacturer_id", "manufacturer_name", "beacon_type", "beacon_id",
        "interval_ema_ms", "mfg_hex", "svc16_hex", "payload_hex",
        "latitude", "longitude", "altitude_m",
    ]

    def __init__(self, path: str) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.handle = p.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=self.FIELDS)
        self.writer.writeheader()

    def write(self, rec: DeviceRecord, seen_at: float) -> None:
        self.writer.writerow({
            "seen_at_epoch": f"{seen_at:.3f}",
            "addr": rec.addr,
            "name": rec.name,
            "rssi": rec.last_rssi,
            "adv_type": rec.adv_type,
            "data_len": rec.data_len,
            "manufacturer_id": "" if rec.manufacturer_id is None else f"0x{rec.manufacturer_id:04X}",
            "manufacturer_name": rec.manufacturer_name,
            "beacon_type": rec.beacon_type,
            "beacon_id": rec.beacon_id,
            "interval_ema_ms": f"{rec.interval_ema_ms:.1f}" if rec.interval_samples else "",
            "mfg_hex": rec.mfg_hex,
            "svc16_hex": rec.svc16_hex,
            "payload_hex": rec.payload_hex,
            "latitude": "" if rec.latitude is None else f"{rec.latitude:.7f}",
            "longitude": "" if rec.longitude is None else f"{rec.longitude:.7f}",
            "altitude_m": "" if rec.altitude_m is None else f"{rec.altitude_m:.2f}",
        })
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def parse_host_port(value: str, default_port: int) -> Tuple[str, int]:
    if ":" not in value:
        return value, default_port
    host, port = value.rsplit(":", 1)
    return host, int(port)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Advanced BLE survey console for Naughty Platypus.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port", required=True, help="CDC serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=0, help="Seconds; 0 runs until Ctrl+C")
    parser.add_argument("--jsonl", help="Raw normalized JSONL event output")
    parser.add_argument("--csv", help="Final per-device inventory CSV")
    parser.add_argument("--events-csv", help="One-row-per-observation analysis CSV")
    parser.add_argument("--db", help="SQLite survey-session database")
    parser.add_argument("--session-name", default="Naughty Platypus survey")
    parser.add_argument("--manufacturer-db", help="Optional Bluetooth SIG/company identifier CSV")
    parser.add_argument("--gpsd", help="GPSD endpoint, e.g. 127.0.0.1:2947")
    parser.add_argument("--lat", type=float, help="Static latitude")
    parser.add_argument("--lon", type=float, help="Static longitude")
    parser.add_argument("--alt", type=float, help="Static altitude in metres")
    parser.add_argument("--tui", action="store_true", help="Interactive curses UI")
    parser.add_argument("--sort", choices=("strongest", "recent"), default="strongest")
    parser.add_argument("--table-interval", type=float, default=5.0)
    parser.add_argument("--max-rows", type=int, default=25)
    parser.add_argument("--dedupe-window", type=float, default=1.5,
                        help="Host duplicate window in seconds; 0 disables")
    parser.add_argument("--print-raw", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--no-stop", action="store_true")
    return parser.parse_args()


def create_gps_provider(args: argparse.Namespace) -> GPSProvider:
    if args.gpsd:
        return GPSDProvider(args.gpsd)
    if args.lat is not None or args.lon is not None:
        if args.lat is None or args.lon is None:
            raise ValueError("--lat and --lon must be supplied together")
        return StaticGPSProvider(args.lat, args.lon, args.alt)
    return GPSProvider()


def send_cmd(ser: serial.Serial, command: str) -> None:
    ser.write((command.strip() + "\r\n").encode("utf-8", errors="replace"))
    ser.flush()


def payload_signature(event: dict) -> str:
    return "|".join([
        str(event.get("adv_type", "")),
        str(event.get("payload_hex", "")),
        str(event.get("mfg", event.get("mfg_hex", ""))),
        str(event.get("svc16", event.get("svc16_hex", ""))),
        str(event.get("name", "")),
    ])


def update_record(
    records: Dict[str, DeviceRecord],
    event: dict,
    company_ids: Dict[int, str],
    fix: GPSFix,
    dedupe_window: float,
) -> Tuple[Optional[DeviceRecord], bool]:
    if event.get("type") not in {"adv", "adv_summary"}:
        return None, False

    addr = str(event.get("addr", "unknown"))
    seen_at = time.time()
    rssi = int(event.get("rssi", -127))
    rec = records.get(addr)
    if rec is None:
        rec = DeviceRecord(addr=addr, first_seen=seen_at, last_seen=seen_at)
        records[addr] = rec
    else:
        delta_ms = max(0.0, (seen_at - rec.last_seen) * 1000.0)
        if 5.0 <= delta_ms <= 60000.0:
            if rec.interval_samples == 0:
                rec.interval_ema_ms = delta_ms
            else:
                rec.interval_ema_ms = (rec.interval_ema_ms * 0.75) + (delta_ms * 0.25)
            rec.interval_samples += 1

    signature = payload_signature(event)
    duplicate = bool(
        dedupe_window > 0
        and signature
        and signature == rec.last_payload_signature
        and (seen_at - rec.last_payload_seen) <= dedupe_window
    )

    rec.last_seen = seen_at
    rec.count += 1
    rec.last_rssi = rssi
    rec.best_rssi = max(rec.best_rssi, rssi)
    rec.worst_rssi = min(rec.worst_rssi, rssi)
    rec.rssi_sum += rssi
    rec.adv_type = int(event.get("adv_type", rec.adv_type))
    rec.data_len = int(event.get("data_len", event.get("ad_len", rec.data_len)))
    rec.payload_hex = str(event.get("payload_hex", rec.payload_hex or ""))
    rec.mfg_hex = str(event.get("mfg", event.get("mfg_hex", rec.mfg_hex or "")))
    rec.svc16_hex = str(event.get("svc16", event.get("svc16_hex", rec.svc16_hex or "")))

    if event.get("name"):
        rec.name = str(event["name"])

    company_id, company_name = manufacturer_lookup(rec.mfg_hex, company_ids)
    if company_id is not None:
        rec.manufacturer_id = company_id
        rec.manufacturer_name = company_name

    beacon = parse_beacon(rec.mfg_hex, rec.svc16_hex)
    if beacon:
        rec.beacon_type = str(beacon.get("type", ""))
        rec.beacon_id = str(beacon.get("id", ""))
        rec.beacon_details = beacon_json(beacon)

    if fix.latitude is not None and fix.longitude is not None:
        rec.latitude = fix.latitude
        rec.longitude = fix.longitude
        rec.altitude_m = fix.altitude_m

    if duplicate:
        rec.suppressed_count += 1
    else:
        rec.emitted_count += 1
        rec.last_payload_signature = signature
        rec.last_payload_seen = seen_at

    return rec, duplicate


def sorted_records(records: Dict[str, DeviceRecord], mode: str) -> Iterable[DeviceRecord]:
    if mode == "recent":
        return sorted(records.values(), key=lambda r: (r.last_seen, r.best_rssi), reverse=True)
    return sorted(records.values(), key=lambda r: (r.best_rssi, r.last_seen), reverse=True)


def print_table(
    records: Dict[str, DeviceRecord],
    start: float,
    mode: str,
    max_rows: int,
    channel_counts: Optional[Dict[int, int]] = None,
) -> None:
    rows = list(sorted_records(records, mode))[:max_rows]
    elapsed = time.time() - start
    total = sum(rec.count for rec in records.values())
    suppressed = sum(rec.suppressed_count for rec in records.values())
    channel_text = "channels=not-exposed"
    if channel_counts:
        channel_text = "channels=" + ",".join(
            f"{channel}:{count}" for channel, count in sorted(channel_counts.items())
        )
    print(
        f"\n=== Naughty Platypus | {elapsed:.1f}s | devices={len(records)} "
        f"events={total} suppressed={suppressed} sort={mode} {channel_text} ==="
    )
    print(
        f"{'Address':34} {'Last':>5} {'Best':>5} {'Seen':>6} "
        f"{'Int(ms)':>8} {'Age':>6} {'Name':22} {'Vendor/Beacon':28}"
    )
    print("-" * 126)
    for rec in rows:
        interval = f"{rec.interval_ema_ms:.0f}" if rec.interval_samples else "-"
        identity = rec.beacon_type or rec.manufacturer_name
        print(
            f"{rec.addr[:34]:34} {rec.last_rssi:5d} {rec.best_rssi:5d} "
            f"{rec.count:6d} {interval:>8} {rec.age_s:6.1f} "
            f"{rec.name[:22]:22} {identity[:28]:28}"
        )


def write_inventory_csv(path: str, records: Dict[str, DeviceRecord]) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "addr", "first_seen_epoch", "last_seen_epoch", "count", "emitted_count",
        "suppressed_count", "last_rssi", "best_rssi", "worst_rssi", "avg_rssi",
        "interval_ema_ms", "name", "adv_type", "data_len", "manufacturer_id",
        "manufacturer_name", "beacon_type", "beacon_id", "beacon_details",
        "mfg_hex", "svc16_hex", "payload_hex", "latitude", "longitude", "altitude_m",
    ]
    with p.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rec in sorted(records.values(), key=lambda item: item.addr):
            row = asdict(rec)
            row["avg_rssi"] = f"{rec.avg_rssi:.2f}"
            row["interval_ema_ms"] = f"{rec.interval_ema_ms:.1f}" if rec.interval_samples else ""
            row["manufacturer_id"] = (
                "" if rec.manufacturer_id is None else f"0x{rec.manufacturer_id:04X}"
            )
            row.pop("interval_samples", None)
            row.pop("last_payload_signature", None)
            row.pop("last_payload_seen", None)
            writer.writerow({key: row.get(key, "") for key in fields})


def open_jsonl(path: Optional[str]) -> Optional[TextIO]:
    if not path:
        return None
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p.open("a", encoding="utf-8")


def normalize_event(event: dict, rec: Optional[DeviceRecord], duplicate: bool, fix: GPSFix) -> dict:
    normalized = dict(event)
    normalized["host_seen_at"] = time.time()
    normalized["host_duplicate"] = duplicate
    if rec:
        normalized["manufacturer_id"] = rec.manufacturer_id
        normalized["manufacturer_name"] = rec.manufacturer_name
        normalized["beacon_type"] = rec.beacon_type
        normalized["beacon_id"] = rec.beacon_id
        normalized["interval_ema_ms"] = round(rec.interval_ema_ms, 1) if rec.interval_samples else None
    if fix.latitude is not None and fix.longitude is not None:
        normalized["gps"] = {
            "lat": fix.latitude,
            "lon": fix.longitude,
            "alt_m": fix.altitude_m,
            "source": fix.source,
            "updated_at": fix.updated_at,
        }
    return normalized


def draw_tui(
    stdscr,
    records: Dict[str, DeviceRecord],
    start: float,
    mode: str,
    fix: GPSFix,
    last_status: str,
    channel_counts: Dict[int, int],
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    total = sum(rec.count for rec in records.values())
    suppressed = sum(rec.suppressed_count for rec in records.values())
    gps_text = "GPS: none"
    if fix.latitude is not None and fix.longitude is not None:
        gps_text = f"GPS: {fix.latitude:.5f},{fix.longitude:.5f} {fix.source}"

    header = (
        f"Naughty Platypus  elapsed={time.time()-start:.1f}s  devices={len(records)} "
        f"events={total} suppressed={suppressed} sort={mode}"
    )
    stdscr.addnstr(0, 0, header, max(0, width - 1), curses.A_BOLD)
    channel_text = "BLE advertising channels: not exposed by current controller callback"
    if channel_counts:
        channel_text = "BLE advertising channels: " + " ".join(
            f"{channel}={count}" for channel, count in sorted(channel_counts.items())
        )
    stdscr.addnstr(1, 0, f"{gps_text} | {channel_text}", max(0, width - 1))
    stdscr.addnstr(
        2, 0,
        "Keys: q quit | s scan | x stop | a active | p passive | r reset | "
        "v toggle sort | d recent view | t strongest view | c channel capability",
        max(0, width - 1),
    )
    stdscr.addnstr(3, 0, f"Status: {last_status}", max(0, width - 1))
    columns = f"{'Address':30} {'RSSI':>5} {'Best':>5} {'Seen':>6} {'Int':>7} {'Age':>6} {'Name':18} {'Identity':22}"
    stdscr.addnstr(5, 0, columns, max(0, width - 1), curses.A_UNDERLINE)

    available = max(0, height - 7)
    for row_idx, rec in enumerate(list(sorted_records(records, mode))[:available], start=6):
        interval = f"{rec.interval_ema_ms:.0f}" if rec.interval_samples else "-"
        identity = rec.beacon_type or rec.manufacturer_name
        line = (
            f"{rec.addr[:30]:30} {rec.last_rssi:5d} {rec.best_rssi:5d} {rec.count:6d} "
            f"{interval:>7} {rec.age_s:6.1f} {rec.name[:18]:18} {identity[:22]:22}"
        )
        stdscr.addnstr(row_idx, 0, line, max(0, width - 1))
    stdscr.refresh()


def run_collector(args: argparse.Namespace, stdscr=None) -> int:
    records: Dict[str, DeviceRecord] = {}
    stop = False
    sort_mode = args.sort
    last_status = "starting"
    company_ids = load_company_ids(args.manufacturer_db)
    channel_counts: Dict[int, int] = {}
    gps = create_gps_provider(args)
    jsonl_file = open_jsonl(args.jsonl)
    events_csv = EventCSV(args.events_csv) if args.events_csv else None
    database = SessionDatabase(args.db, args.port, args.session_name) if args.db else None

    def handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    start = time.time()
    next_table = start + args.table_interval
    next_draw = start

    try:
        with serial.Serial(args.port, args.baud, timeout=0.1) as ser:
            time.sleep(0.5)
            if not args.no_start:
                send_cmd(ser, "scan")
                last_status = "scan command sent"

            if stdscr is not None:
                curses.curs_set(0)
                stdscr.nodelay(True)
                stdscr.timeout(0)

            while not stop:
                now = time.time()
                if args.duration and (now - start) >= args.duration:
                    break

                fix = gps.poll()

                if stdscr is not None:
                    key = stdscr.getch()
                    if key != -1:
                        command_map = {
                            ord("s"): "scan",
                            ord("x"): "stop",
                            ord("a"): "active",
                            ord("p"): "passive",
                            ord("r"): "reset",
                        }
                        if key in (ord("q"), 27):
                            stop = True
                        elif key == ord("v"):
                            sort_mode = "recent" if sort_mode == "strongest" else "strongest"
                            last_status = f"sort={sort_mode}"
                        elif key == ord("d"):
                            sort_mode = "recent"
                            last_status = "sort=recent"
                        elif key == ord("t"):
                            sort_mode = "strongest"
                            last_status = "sort=strongest"
                        elif key == ord("c"):
                            if channel_counts:
                                last_status = "channel counts " + ", ".join(
                                    f"{ch}={count}" for ch, count in sorted(channel_counts.items())
                                )
                            else:
                                last_status = (
                                    "advertising channel index is not exposed by this firmware/controller API"
                                )
                        elif key in command_map:
                            cmd = command_map[key]
                            send_cmd(ser, cmd)
                            last_status = f"sent {cmd}"

                line = ser.readline().decode("utf-8", errors="replace").strip()
                if line.startswith("{"):
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        event = None

                    if event is not None:
                        raw_channel = event.get("channel", event.get("primary_channel"))
                        if isinstance(raw_channel, int) and 0 <= raw_channel <= 255:
                            channel_counts[raw_channel] = channel_counts.get(raw_channel, 0) + 1

                        rec, duplicate = update_record(
                            records, event, company_ids, fix, args.dedupe_window
                        )
                        normalized = normalize_event(event, rec, duplicate, fix)

                        if jsonl_file:
                            jsonl_file.write(json.dumps(normalized, separators=(",", ":")) + "\n")
                            jsonl_file.flush()

                        if args.print_raw and stdscr is None:
                            print(json.dumps(normalized, indent=2, sort_keys=True))

                        if rec and not duplicate:
                            if events_csv:
                                events_csv.write(rec, normalized["host_seen_at"])
                            if database:
                                database.add_observation(rec, normalized["host_seen_at"])

                        if event.get("type") in {"survey_status", "queue_status", "scan_mode", "channel_stats"}:
                            last_status = json.dumps(event, separators=(",", ":"))[:160]

                now = time.time()
                if stdscr is not None and now >= next_draw:
                    draw_tui(
                        stdscr, records, start, sort_mode, fix, last_status, channel_counts
                    )
                    next_draw = now + 0.25
                elif stdscr is None and now >= next_table:
                    print_table(records, start, sort_mode, args.max_rows, channel_counts)
                    next_table = now + args.table_interval

            if not args.no_stop:
                try:
                    send_cmd(ser, "stop")
                except Exception:
                    pass
    finally:
        gps.close()
        if jsonl_file:
            jsonl_file.close()
        if events_csv:
            events_csv.close()
        if database:
            database.finalize(records)

    if stdscr is None:
        print_table(records, start, sort_mode, args.max_rows, channel_counts)
    if args.csv:
        write_inventory_csv(args.csv, records)
        if stdscr is None:
            print(f"\nWrote inventory CSV: {args.csv}")
    if args.db and stdscr is None:
        print(f"Wrote SQLite session: {args.db}")
    return 0


def main() -> int:
    args = parse_args()
    if args.tui:
        return curses.wrapper(lambda stdscr: run_collector(args, stdscr))
    return run_collector(args)


if __name__ == "__main__":
    raise SystemExit(main())
