"""Normalización reproducible y pseudonimizada de eventos ADFS."""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import ipaddress
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from adfs_schema import EVENT_DEFINITIONS, SOURCE_COLUMNS

OUTPUT_COLUMNS = [
    "record_id",
    "source_event_id",
    "deduplication_key",
    "event_type_id",
    "event_name",
    "event_class",
    "event_time_utc",
    "event_time_source",
    "created_at_utc",
    "updated_at_utc",
    "log_source_key",
    "user_key",
    "user_id_format",
    "client_ip_key",
    "client_ip_version",
    "client_ip_scope",
    "relying_party",
    "event_count",
    "quality_flags",
]
REJECTED_COLUMNS = [*OUTPUT_COLUMNS, "rejection_reason"]


@dataclass(frozen=True)
class NormalizationConfig:
    minimum_year: int
    rejection_flags: frozenset[str]

    @classmethod
    def from_file(cls, path: Path) -> NormalizationConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            minimum_year=int(raw["minimum_year"]),
            rejection_flags=frozenset(raw["rejection_flags"]),
        )


def parse_timestamp(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_timestamp(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def canonicalize_user(value: str) -> tuple[str, str]:
    normalized = value.strip().casefold()
    if not normalized:
        return "", "missing"
    if "\\" in normalized:
        return normalized.rsplit("\\", 1)[1], "domain_backslash_user"
    if "@" in normalized:
        return normalized.split("@", 1)[0], "email_like"
    return normalized, "other"


def pseudonymize(value: str, secret: bytes, prefix: str) -> str:
    if not value:
        return ""
    digest = hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _deduplication_key(normalized: dict[str, str | int]) -> str:
    source_event_id = str(normalized["source_event_id"])
    if source_event_id:
        return f"event:{source_event_id}"
    material = "|".join(
        str(normalized[field])
        for field in (
            "event_time_utc",
            "event_type_id",
            "event_class",
            "user_key",
            "client_ip_key",
            "relying_party",
            "log_source_key",
            "event_count",
        )
    )
    return "fingerprint:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def normalize_record(
    record: dict[str, str], secret: bytes, minimum_year: int
) -> dict[str, str | int]:
    flags: list[str] = []
    event_name = record["event_name"].strip()
    event_type_id = record["event_type_id"].strip()
    source_event_id = record["event_id"].strip()
    if not source_event_id:
        flags.append("MISSING_SOURCE_EVENT_ID")

    expected_type, event_class = EVENT_DEFINITIONS.get(event_name, (None, "other"))
    if expected_type is None:
        flags.append("UNKNOWN_EVENT_NAME")
    elif event_type_id != expected_type:
        flags.append("EVENT_TYPE_MISMATCH")

    origin_time = parse_timestamp(record["event_time_origen"])
    processed_time = parse_timestamp(record["event_time"])
    chosen_time = origin_time if origin_time is not None else processed_time
    time_source = "event_time_origen" if origin_time is not None else "event_time"
    if chosen_time is None or chosen_time.year < minimum_year:
        flags.append("INVALID_EVENT_TIME")
        chosen_time = None
        time_source = ""

    created_at = parse_timestamp(record["created_at"])
    updated_at = parse_timestamp(record["updated_at"])
    if created_at is None:
        flags.append("INVALID_CREATED_AT")
    if chosen_time is not None and created_at is not None and created_at < chosen_time:
        flags.append("CREATED_BEFORE_EVENT")

    canonical_user, user_format = canonicalize_user(record["custom_user_id"])
    if not canonical_user:
        flags.append("MISSING_USER_ID")

    client_ip_key = ""
    client_ip_version: str | int = ""
    client_ip_scope = ""
    client_ip_raw = record["custom_ip_address"].strip()
    if not client_ip_raw:
        flags.append("MISSING_CLIENT_IP")
    else:
        try:
            client_ip = ipaddress.ip_address(client_ip_raw)
            client_ip_key = pseudonymize(client_ip.compressed, secret, "ip")
            client_ip_version = client_ip.version
            client_ip_scope = "private" if client_ip.is_private else "public"
        except ValueError:
            flags.append("INVALID_CLIENT_IP")

    try:
        event_count = int(record["event_count"].strip())
        if event_count < 1:
            raise ValueError
    except ValueError:
        event_count = 1
        flags.append("INVALID_EVENT_COUNT")

    relying_party = record["custom_relying_party"].strip()
    if relying_party.casefold() == "n/a":
        relying_party = ""

    normalized: dict[str, str | int] = {
        "record_id": record["id"].strip(),
        "source_event_id": source_event_id,
        "deduplication_key": "",
        "event_type_id": event_type_id,
        "event_name": event_name,
        "event_class": event_class,
        "event_time_utc": format_timestamp(chosen_time),
        "event_time_source": time_source,
        "created_at_utc": format_timestamp(created_at),
        "updated_at_utc": format_timestamp(updated_at),
        "log_source_key": pseudonymize(record["log_source"].strip(), secret, "src"),
        "user_key": pseudonymize(canonical_user, secret, "usr"),
        "user_id_format": user_format,
        "client_ip_key": client_ip_key,
        "client_ip_version": client_ip_version,
        "client_ip_scope": client_ip_scope,
        "relying_party": relying_party,
        "event_count": event_count,
        "quality_flags": ";".join(flags),
    }
    normalized["deduplication_key"] = _deduplication_key(normalized)
    return normalized


def rejection_reasons(normalized: dict[str, str | int], config: NormalizationConfig) -> list[str]:
    flags = set(str(normalized["quality_flags"]).split(";"))
    return sorted(flag for flag in flags if flag in config.rejection_flags)


def _malformed_rejection(row: list[str]) -> dict[str, str | int]:
    digest = hashlib.sha256("\x1f".join(row).encode("utf-8")).hexdigest()
    rejected = {column: "" for column in OUTPUT_COLUMNS}
    rejected["deduplication_key"] = f"malformed:{digest}"
    rejected["quality_flags"] = "MALFORMED_COLUMN_COUNT"
    rejected["rejection_reason"] = "MALFORMED_COLUMN_COUNT"
    return rejected


def _read_secret(key_file: Path | None, environment_name: str) -> bytes:
    value = ""
    if key_file:
        if not key_file.is_file():
            raise FileNotFoundError(f"No existe el archivo de clave: {key_file}")
        value = key_file.read_text(encoding="utf-8").strip()
    if not value:
        value = os.environ.get(environment_name, "").strip()
    if not value:
        raise RuntimeError(f"Falta --pseudonym-key-file o la variable {environment_name}")
    return value.encode("utf-8")


def normalize_csv(
    input_csv: Path,
    normalized_output: Path,
    rejected_output: Path,
    stats_output: Path,
    secret: bytes,
    config: NormalizationConfig,
    limit: int | None = None,
) -> dict:
    normalized_output.parent.mkdir(parents=True, exist_ok=True)
    rejected_output.parent.mkdir(parents=True, exist_ok=True)
    stats: dict[str, object] = {
        "input_rows": 0,
        "valid_rows": 0,
        "rejected_rows": 0,
        "duplicate_rows": 0,
        "malformed_rows": 0,
        "accepted_with_warnings": 0,
        "event_classes": Counter(),
        "quality_flags": Counter(),
        "rejection_reasons": Counter(),
    }
    seen_keys: set[str] = set()

    with (
        input_csv.open("r", encoding="utf-8-sig", newline="") as source,
        normalized_output.open("w", encoding="utf-8", newline="") as valid_file,
        rejected_output.open("w", encoding="utf-8", newline="") as rejected_file,
    ):
        reader = csv.reader(source)
        valid_writer = csv.DictWriter(valid_file, fieldnames=OUTPUT_COLUMNS)
        rejected_writer = csv.DictWriter(rejected_file, fieldnames=REJECTED_COLUMNS)
        valid_writer.writeheader()
        rejected_writer.writeheader()

        for row in reader:
            if not row or all(not value.strip() for value in row):
                continue
            stats["input_rows"] = int(stats["input_rows"]) + 1
            if len(row) != len(SOURCE_COLUMNS):
                stats["malformed_rows"] = int(stats["malformed_rows"]) + 1
                stats["rejected_rows"] = int(stats["rejected_rows"]) + 1
                stats["rejection_reasons"]["MALFORMED_COLUMN_COUNT"] += 1
                rejected_writer.writerow(_malformed_rejection(row))
                continue

            normalized = normalize_record(
                dict(zip(SOURCE_COLUMNS, row, strict=True)), secret, config.minimum_year
            )
            key = str(normalized["deduplication_key"])
            reasons = rejection_reasons(normalized, config)
            if key in seen_keys:
                reasons.append("DUPLICATE_EVENT")
                stats["duplicate_rows"] = int(stats["duplicate_rows"]) + 1
            else:
                seen_keys.add(key)

            flags = [flag for flag in str(normalized["quality_flags"]).split(";") if flag]
            for flag in flags:
                stats["quality_flags"][flag] += 1

            if reasons:
                rejected = {**normalized, "rejection_reason": ";".join(sorted(set(reasons)))}
                rejected_writer.writerow(rejected)
                stats["rejected_rows"] = int(stats["rejected_rows"]) + 1
                for reason in set(reasons):
                    stats["rejection_reasons"][reason] += 1
            else:
                valid_writer.writerow(normalized)
                stats["valid_rows"] = int(stats["valid_rows"]) + 1
                stats["event_classes"][normalized["event_class"]] += 1
                if flags:
                    stats["accepted_with_warnings"] = int(stats["accepted_with_warnings"]) + 1

            if limit is not None and int(stats["input_rows"]) >= limit:
                break

    serializable = {
        **stats,
        "output_rows": stats["valid_rows"],
        "consistent_rows": int(stats["valid_rows"]) - int(stats["accepted_with_warnings"]),
        "inconsistent_rows": stats["rejected_rows"],
        "event_classes": dict(stats["event_classes"]),
        "quality_flags": dict(stats["quality_flags"]),
        "rejection_reasons": dict(stats["rejection_reasons"]),
    }
    stats_output.parent.mkdir(parents=True, exist_ok=True)
    stats_output.write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return serializable


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rejected-output", type=Path, required=True)
    parser.add_argument("--stats-output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/normalization.json"))
    parser.add_argument("--pseudonym-key-env", default="SOC_PSEUDONYM_KEY")
    parser.add_argument("--pseudonym-key-file", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    result = normalize_csv(
        input_csv=args.input_csv,
        normalized_output=args.output,
        rejected_output=args.rejected_output,
        stats_output=args.stats_output,
        secret=_read_secret(args.pseudonym_key_file, args.pseudonym_key_env),
        config=NormalizationConfig.from_file(args.config),
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
