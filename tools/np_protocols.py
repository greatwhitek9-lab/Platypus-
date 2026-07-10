#!/usr/bin/env python3
"""Protocol and manufacturer decoders for Naughty Platypus host tools."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import quote

COMMON_COMPANY_IDS: Dict[int, str] = {
    0x0000: "Ericsson Technology Licensing",
    0x0001: "Nokia Mobile Phones",
    0x0002: "Intel Corp.",
    0x0003: "IBM Corp.",
    0x0004: "Toshiba Corp.",
    0x0005: "3Com",
    0x0006: "Microsoft",
    0x0007: "Lucent",
    0x0008: "Motorola",
    0x004C: "Apple, Inc.",
    0x0059: "Nordic Semiconductor ASA",
    0x0075: "Samsung Electronics Co. Ltd.",
    0x00E0: "Google",
}

EDDYSTONE_URL_PREFIXES = {
    0x00: "http://www.",
    0x01: "https://www.",
    0x02: "http://",
    0x03: "https://",
}

EDDYSTONE_URL_SUFFIXES = {
    0x00: ".com/",
    0x01: ".org/",
    0x02: ".edu/",
    0x03: ".net/",
    0x04: ".info/",
    0x05: ".biz/",
    0x06: ".gov/",
    0x07: ".com",
    0x08: ".org",
    0x09: ".edu",
    0x0A: ".net",
    0x0B: ".info",
    0x0C: ".biz",
    0x0D: ".gov",
}


def _clean_hex(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch in "0123456789abcdef")


def _bytes(value: str) -> bytes:
    cleaned = _clean_hex(value)
    if len(cleaned) % 2:
        cleaned = cleaned[:-1]
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return b""


def load_company_ids(path: Optional[str] = None) -> Dict[int, str]:
    """Load Bluetooth company identifiers from a CSV, layered over common IDs."""
    result = dict(COMMON_COMPANY_IDS)
    if not path:
        return result

    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"manufacturer database not found: {p}")

    with p.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return result

        normalized = {name.lower().strip(): name for name in reader.fieldnames}
        id_keys = ("decimal", "value", "company identifier", "company_id", "id", "hex")
        name_keys = ("company", "company name", "organization", "name")
        id_field = next((normalized[k] for k in id_keys if k in normalized), None)
        name_field = next((normalized[k] for k in name_keys if k in normalized), None)
        if not id_field or not name_field:
            raise ValueError("manufacturer CSV needs an ID column and a company/name column")

        for row in reader:
            raw_id = (row.get(id_field) or "").strip()
            company = (row.get(name_field) or "").strip()
            if not raw_id or not company:
                continue
            try:
                base = 16 if raw_id.lower().startswith("0x") or any(c in "abcdefABCDEF" for c in raw_id) else 10
                company_id = int(raw_id, base)
            except ValueError:
                continue
            if 0 <= company_id <= 0xFFFF:
                result[company_id] = company

    return result


def manufacturer_lookup(mfg_hex: str, company_ids: Dict[int, str]) -> Tuple[Optional[int], str]:
    raw = _bytes(mfg_hex)
    if len(raw) < 2:
        return None, ""
    company_id = int.from_bytes(raw[:2], "little")
    return company_id, company_ids.get(company_id, f"Unknown company 0x{company_id:04X}")


def _format_uuid(raw: bytes) -> str:
    if len(raw) != 16:
        return raw.hex()
    h = raw.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def parse_ibeacon(mfg_hex: str) -> Optional[dict]:
    raw = _bytes(mfg_hex)
    if len(raw) < 25 or raw[:4] != bytes.fromhex("4c000215"):
        return None
    uuid = _format_uuid(raw[4:20])
    major = int.from_bytes(raw[20:22], "big")
    minor = int.from_bytes(raw[22:24], "big")
    tx_power = int.from_bytes(raw[24:25], "big", signed=True)
    return {
        "type": "iBeacon",
        "id": f"{uuid}:{major}:{minor}",
        "uuid": uuid,
        "major": major,
        "minor": minor,
        "tx_power": tx_power,
    }


def parse_altbeacon(mfg_hex: str) -> Optional[dict]:
    raw = _bytes(mfg_hex)
    if len(raw) < 26 or raw[2:4] != bytes.fromhex("beac"):
        return None
    company_id = int.from_bytes(raw[:2], "little")
    beacon_id = raw[4:24].hex()
    reference_rssi = int.from_bytes(raw[24:25], "big", signed=True)
    reserved = raw[25:].hex()
    return {
        "type": "AltBeacon",
        "id": beacon_id,
        "company_id": company_id,
        "reference_rssi": reference_rssi,
        "reserved": reserved,
    }


def _decode_eddystone_url(encoded: bytes) -> str:
    if not encoded:
        return ""
    parts = [EDDYSTONE_URL_PREFIXES.get(encoded[0], "")]
    for value in encoded[1:]:
        if value in EDDYSTONE_URL_SUFFIXES:
            parts.append(EDDYSTONE_URL_SUFFIXES[value])
        elif 32 <= value <= 126:
            parts.append(chr(value))
        else:
            parts.append(quote(bytes([value])))
    return "".join(parts)


def parse_eddystone(svc16_hex: str) -> Optional[dict]:
    raw = _bytes(svc16_hex)
    if len(raw) < 3 or raw[:2] != bytes.fromhex("aafe"):
        return None

    frame = raw[2]
    if frame == 0x00 and len(raw) >= 20:
        tx_power = int.from_bytes(raw[3:4], "big", signed=True)
        namespace = raw[4:14].hex()
        instance = raw[14:20].hex()
        return {
            "type": "Eddystone-UID",
            "id": f"{namespace}:{instance}",
            "namespace": namespace,
            "instance": instance,
            "tx_power": tx_power,
        }

    if frame == 0x10 and len(raw) >= 5:
        tx_power = int.from_bytes(raw[3:4], "big", signed=True)
        url = _decode_eddystone_url(raw[4:])
        return {
            "type": "Eddystone-URL",
            "id": url,
            "url": url,
            "tx_power": tx_power,
        }

    if frame == 0x20 and len(raw) >= 16:
        version = raw[3]
        battery_mv = int.from_bytes(raw[4:6], "big")
        temp_raw = int.from_bytes(raw[6:8], "big", signed=True)
        adv_count = int.from_bytes(raw[8:12], "big")
        sec_count = int.from_bytes(raw[12:16], "big") / 10.0
        return {
            "type": "Eddystone-TLM",
            "id": f"tlm:{adv_count}:{battery_mv}",
            "version": version,
            "battery_mv": battery_mv,
            "temperature_c": round(temp_raw / 256.0, 2),
            "adv_count": adv_count,
            "uptime_s": sec_count,
        }

    if frame == 0x30 and len(raw) >= 11:
        tx_power = int.from_bytes(raw[3:4], "big", signed=True)
        eid = raw[4:12].hex()
        return {
            "type": "Eddystone-EID",
            "id": eid,
            "eid": eid,
            "tx_power": tx_power,
        }

    return {
        "type": f"Eddystone-Unknown-0x{frame:02X}",
        "id": raw[3:].hex(),
        "frame_type": frame,
        "raw": raw.hex(),
    }


def parse_fast_pair(svc16_hex: str) -> Optional[dict]:
    raw = _bytes(svc16_hex)
    if len(raw) < 5 or raw[:2] != bytes.fromhex("2cfe"):
        return None
    model_id = raw[2:5].hex().upper()
    return {
        "type": "Fast Pair",
        "id": model_id,
        "model_id": model_id,
        "extra": raw[5:].hex(),
    }


def parse_beacon(mfg_hex: str, svc16_hex: str) -> Optional[dict]:
    for parser, value in (
        (parse_ibeacon, mfg_hex),
        (parse_altbeacon, mfg_hex),
        (parse_eddystone, svc16_hex),
        (parse_fast_pair, svc16_hex),
    ):
        parsed = parser(value)
        if parsed:
            return parsed
    return None


def beacon_json(beacon: Optional[dict]) -> str:
    return json.dumps(beacon or {}, separators=(",", ":"), sort_keys=True)
