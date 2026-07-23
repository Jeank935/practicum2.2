"""Perfil reproducible para el CSV de eventos de seguridad ADFS.

El archivo de origen no contiene encabezados. Este script aplica el esquema
confirmado por el propietario de los datos y genera un resumen sin publicar
usuarios ni direcciones IP externas concretas.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adfs_schema import EVENT_DEFINITIONS, SOURCE_COLUMNS  # noqa: E402

COLUMNS = SOURCE_COLUMNS

SENSITIVE_COLUMNS = {
    "log_source",
    "source_ip",
    "destination_ip",
    "username",
    "custom_user_id",
    "custom_ip_address",
    "custom_relying_party",
    "custom_message",
}

TIMESTAMP_COLUMNS = {
    "event_time",
    "created_at",
    "updated_at",
    "event_time_origen",
}

IP_COLUMNS = {"source_ip", "destination_ip", "custom_ip_address"}

EXPECTED_EVENT_TYPES = {
    event_name: event_type for event_name, (event_type, _) in EVENT_DEFINITIONS.items()
}


def parse_timestamp(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def classify_event(event_name: str, low_level_category: str) -> str:
    combined = f"{event_name} {low_level_category}".casefold()
    if "lockout" in combined or "bloque" in combined:
        return "lockout"
    if "failure" in combined or "error" in combined or "failed" in combined:
        return "failure"
    if "success" in combined or "successful" in combined:
        return "success"
    return "other"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_hash = hashlib.sha256()
    with args.input_csv.open("rb") as binary_source:
        for chunk in iter(lambda: binary_source.read(1024 * 1024), b""):
            source_hash.update(chunk)

    counters = {
        name: {
            "blank": 0,
            "integer_like": 0,
            "timestamp_valid": 0,
            "timestamp_invalid": 0,
            "distinct": set(),
            "top": Counter(),
        }
        for name in COLUMNS
    }
    timestamp_ranges = {name: {"minimum": None, "maximum": None} for name in TIMESTAMP_COLUMNS}
    ip_quality = {
        name: Counter({"valid": 0, "private": 0, "public": 0, "invalid": 0}) for name in IP_COLUMNS
    }
    event_classes = Counter()
    event_type_cross_tab: dict[str, Counter] = defaultdict(Counter)
    event_time_years = Counter()
    event_time_days = Counter()
    class_users: dict[str, set[str]] = defaultdict(set)
    class_ips: dict[str, set[str]] = defaultdict(set)
    class_missing_users = Counter()
    class_missing_ips = Counter()
    user_id_formats = Counter()
    full_row_hashes: set[bytes] = set()
    duplicate_rows = 0
    malformed_rows = 0
    total_rows = 0
    ingestion_delays: list[float] = []
    origin_time_deltas: list[float] = []
    safe_anomaly_examples: list[dict[str, str]] = []

    with args.input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for _row_number, row in enumerate(reader, start=1):
            if not row or all(not value.strip() for value in row):
                continue

            total_rows += 1
            if len(row) != len(COLUMNS):
                malformed_rows += 1
                continue

            digest = hashlib.blake2b("\x1f".join(row).encode("utf-8"), digest_size=16).digest()
            if digest in full_row_hashes:
                duplicate_rows += 1
            else:
                full_row_hashes.add(digest)

            record = dict(zip(COLUMNS, row, strict=True))
            event_class = classify_event(record["event_name"], record["low_level_category"])
            event_classes[event_class] += 1
            event_type_cross_tab[record["event_name"]][record["event_type_id"]] += 1

            user_id = record["custom_user_id"].strip()
            client_ip = record["custom_ip_address"].strip()
            if user_id:
                class_users[event_class].add(user_id)
                if "@" in user_id:
                    user_id_formats["email_like"] += 1
                elif "\\" in user_id:
                    user_id_formats["domain_backslash_user"] += 1
                else:
                    user_id_formats["other"] += 1
            else:
                class_missing_users[event_class] += 1
            if client_ip:
                class_ips[event_class].add(client_ip)
            else:
                class_missing_ips[event_class] += 1

            event_time = parse_timestamp(record["event_time"])
            created_at = parse_timestamp(record["created_at"])
            origin_time = parse_timestamp(record["event_time_origen"])
            if event_time is not None:
                event_time_years[str(event_time.year)] += 1
                event_time_days[event_time.date().isoformat()] += 1
            if event_time is not None and origin_time is not None:
                origin_time_deltas.append((event_time - origin_time).total_seconds())
            expected_type = EXPECTED_EVENT_TYPES.get(record["event_name"])
            has_bad_time = event_time is not None and event_time.year < 2020
            has_type_mismatch = (
                expected_type is not None and record["event_type_id"] != expected_type
            )
            if (has_bad_time or has_type_mismatch) and len(safe_anomaly_examples) < 20:
                safe_anomaly_examples.append(
                    {
                        "id": record["id"],
                        "event_name": record["event_name"],
                        "event_type_id": record["event_type_id"],
                        "event_time": record["event_time"],
                        "created_at": record["created_at"],
                        "event_time_origen": record["event_time_origen"],
                        "quality_issue": ",".join(
                            issue
                            for issue, present in (
                                ("EVENT_TIME_BEFORE_2020", has_bad_time),
                                ("EVENT_TYPE_MISMATCH", has_type_mismatch),
                            )
                            if present
                        ),
                    }
                )
            if event_time is not None and created_at is not None:
                ingestion_delays.append((created_at - event_time).total_seconds())

            for name, raw_value in record.items():
                value = raw_value.strip()
                profile = counters[name]
                if not value:
                    profile["blank"] += 1
                    continue

                profile["distinct"].add(value)
                if name not in SENSITIVE_COLUMNS:
                    profile["top"][value] += 1

                try:
                    int(value)
                    profile["integer_like"] += 1
                except ValueError:
                    pass

                if name in TIMESTAMP_COLUMNS:
                    timestamp = parse_timestamp(value)
                    if timestamp is None:
                        profile["timestamp_invalid"] += 1
                    else:
                        profile["timestamp_valid"] += 1
                        current = timestamp_ranges[name]
                        current["minimum"] = (
                            timestamp
                            if current["minimum"] is None
                            else min(current["minimum"], timestamp)
                        )
                        current["maximum"] = (
                            timestamp
                            if current["maximum"] is None
                            else max(current["maximum"], timestamp)
                        )

                if name in IP_COLUMNS:
                    try:
                        address = ipaddress.ip_address(value)
                        ip_quality[name]["valid"] += 1
                        ip_quality[name]["private" if address.is_private else "public"] += 1
                    except ValueError:
                        ip_quality[name]["invalid"] += 1

    column_profiles = []
    for name in COLUMNS:
        profile = counters[name]
        nonblank = total_rows - profile["blank"]
        column_profiles.append(
            {
                "column": name,
                "blank_count": profile["blank"],
                "blank_percent": round((profile["blank"] / total_rows) * 100, 2)
                if total_rows
                else 0,
                "nonblank_count": nonblank,
                "distinct_count": len(profile["distinct"]),
                "integer_like_count": profile["integer_like"],
                "timestamp_valid_count": profile["timestamp_valid"],
                "timestamp_invalid_count": profile["timestamp_invalid"],
                "top_values": (
                    "suppressed_sensitive_field"
                    if name in SENSITIVE_COLUMNS
                    else [
                        {"value": value, "count": count}
                        for value, count in profile["top"].most_common(10)
                    ]
                ),
            }
        )

    output = {
        "source_file": str(args.input_csv),
        "source_sha256": source_hash.hexdigest(),
        "schema": COLUMNS,
        "row_count": total_rows,
        "valid_width_rows": total_rows - malformed_rows,
        "malformed_width_rows": malformed_rows,
        "duplicate_full_rows": duplicate_rows,
        "column_profiles": column_profiles,
        "timestamp_ranges": {
            name: {
                "minimum": values["minimum"].isoformat() if values["minimum"] else None,
                "maximum": values["maximum"].isoformat() if values["maximum"] else None,
            }
            for name, values in timestamp_ranges.items()
        },
        "ip_quality": {name: dict(counts) for name, counts in ip_quality.items()},
        "preliminary_event_classes": dict(event_classes),
        "event_type_cross_tab": {
            event_name: dict(counts) for event_name, counts in event_type_cross_tab.items()
        },
        "event_time_years": dict(sorted(event_time_years.items())),
        "event_time_daily_counts": dict(sorted(event_time_days.items())),
        "event_class_coverage": {
            event_class: {
                "rows": event_classes[event_class],
                "distinct_users": len(class_users[event_class]),
                "distinct_client_ips": len(class_ips[event_class]),
                "missing_user_rows": class_missing_users[event_class],
                "missing_client_ip_rows": class_missing_ips[event_class],
            }
            for event_class in sorted(event_classes)
        },
        "user_id_formats": dict(user_id_formats),
        "ingestion_delay_seconds": {
            "count": len(ingestion_delays),
            "negative_count": sum(value < 0 for value in ingestion_delays),
            "minimum": min(ingestion_delays) if ingestion_delays else None,
            "median": median(ingestion_delays) if ingestion_delays else None,
            "p95": percentile(ingestion_delays, 0.95),
            "maximum": max(ingestion_delays) if ingestion_delays else None,
        },
        "event_time_minus_origin_seconds": {
            "count": len(origin_time_deltas),
            "minimum": min(origin_time_deltas) if origin_time_deltas else None,
            "median": median(origin_time_deltas) if origin_time_deltas else None,
            "p95": percentile(origin_time_deltas, 0.95),
            "maximum": max(origin_time_deltas) if origin_time_deltas else None,
        },
        "safe_anomaly_examples": safe_anomaly_examples,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
