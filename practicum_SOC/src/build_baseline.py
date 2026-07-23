"""Construye la línea base de comportamiento desde eventos normalizados."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

EVENT_CLASSES = ("success", "failure", "lockout", "other")
REQUIRED_COLUMNS = {
    "event_class",
    "event_time_utc",
    "user_key",
    "client_ip_key",
    "relying_party",
    "event_count",
}


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def percentile(values: list[int | float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return float(ordered[index])


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def class_counter() -> Counter:
    return Counter({event_class: 0 for event_class in EVENT_CLASSES})


def new_entity_stats() -> dict:
    return {
        "classes": class_counter(),
        "total": 0,
        "users": set(),
        "ips": set(),
        "apps": set(),
        "hours": set(),
        "first_seen": None,
        "last_seen": None,
    }


def update_entity(
    stats: dict,
    event_class: str,
    weight: int,
    timestamp: datetime,
    user_key: str,
    client_ip_key: str,
    relying_party: str,
) -> None:
    normalized_class = event_class if event_class in EVENT_CLASSES else "other"
    stats["classes"][normalized_class] += weight
    stats["total"] += weight
    if user_key:
        stats["users"].add(user_key)
    if client_ip_key:
        stats["ips"].add(client_ip_key)
    if relying_party:
        stats["apps"].add(relying_party)
    stats["hours"].add(timestamp.hour)
    stats["first_seen"] = (
        timestamp if stats["first_seen"] is None else min(stats["first_seen"], timestamp)
    )
    stats["last_seen"] = (
        timestamp if stats["last_seen"] is None else max(stats["last_seen"], timestamp)
    )


def finalize_entity(identifier_name: str, identifier: str, stats: dict) -> dict:
    success = stats["classes"]["success"]
    failure = stats["classes"]["failure"]
    lockout = stats["classes"]["lockout"]
    authentication_attempts = success + failure
    return {
        identifier_name: identifier,
        "total_events": stats["total"],
        "success_count": success,
        "failure_count": failure,
        "lockout_count": lockout,
        "failure_rate": rate(failure, authentication_attempts),
        "adverse_event_rate": rate(failure + lockout, stats["total"]),
        "distinct_users": len(stats["users"]),
        "distinct_client_ips": len(stats["ips"]),
        "distinct_relying_parties": len(stats["apps"]),
        "active_hour_count": len(stats["hours"]),
        "first_seen_local": stats["first_seen"].isoformat() if stats["first_seen"] else "",
        "last_seen_local": stats["last_seen"].isoformat() if stats["last_seen"] else "",
    }


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_weight(row: dict[str, str]) -> int:
    try:
        return max(1, int(row.get("event_count", "1")))
    except ValueError:
        return 1


@dataclass(frozen=True)
class DailyScan:
    stats: dict[str, dict]
    input_rows: int
    invalid_time_rows: int


@dataclass
class TrainingAggregation:
    hourly_by_day: dict[tuple[str, int], Counter] = field(
        default_factory=lambda: defaultdict(class_counter)
    )
    user_stats: dict[str, dict] = field(default_factory=lambda: defaultdict(new_entity_stats))
    ip_stats: dict[str, dict] = field(default_factory=lambda: defaultdict(new_entity_stats))
    app_stats: dict[str, dict] = field(default_factory=lambda: defaultdict(new_entity_stats))
    user_hour_stats: dict[tuple[str, int], Counter] = field(
        default_factory=lambda: defaultdict(class_counter)
    )
    user_ip_stats: dict[tuple[str, str], dict] = field(
        default_factory=lambda: defaultdict(new_entity_stats)
    )
    user_app_stats: dict[tuple[str, str], dict] = field(
        default_factory=lambda: defaultdict(new_entity_stats)
    )
    class_totals: Counter = field(default_factory=class_counter)
    event_count: int = 0
    distinct_users: set[str] = field(default_factory=set)
    distinct_ips: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ProfileRows:
    users: list[dict]
    ips: list[dict]
    apps: list[dict]
    user_hours: list[dict]
    user_ips: list[dict]
    user_apps: list[dict]


def _scan_daily(input_csv: Path, local_timezone: ZoneInfo) -> DailyScan:
    daily_stats: dict[str, dict] = defaultdict(new_entity_stats)
    input_rows = 0
    invalid_time_rows = 0
    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Faltan columnas normalizadas: {sorted(missing)}")
        for row in reader:
            input_rows += 1
            event_time = parse_timestamp(row["event_time_utc"])
            if event_time is None:
                invalid_time_rows += 1
                continue
            local_time = event_time.astimezone(local_timezone)
            day_key = local_time.date().isoformat()
            update_entity(
                daily_stats[day_key],
                row["event_class"],
                read_weight(row),
                local_time,
                row["user_key"],
                row["client_ip_key"],
                row["relying_party"],
            )
    return DailyScan(dict(daily_stats), input_rows, invalid_time_rows)


def _select_period_days(scan: DailyScan, config: dict) -> tuple[set[str], set[str]]:
    minimum_events = int(config["minimum_events_per_day"])
    minimum_hours = int(config["minimum_active_hours_per_day"])
    training_start = str(config.get("training_start_local", ""))
    training_end = str(config.get("training_end_local", ""))
    evaluation_start = str(config.get("evaluation_start_local", ""))

    baseline_days = {
        day
        for day, stats in scan.stats.items()
        if stats["total"] >= minimum_events
        and len(stats["hours"]) >= minimum_hours
        and (not training_start or day >= training_start)
        and (not training_end or day <= training_end)
    }
    if not baseline_days:
        raise ValueError("Ningún día cumple los criterios mínimos para la línea base")
    evaluation_days = {
        day
        for day in scan.stats
        if (not evaluation_start or day >= evaluation_start)
        and (not training_end or day > training_end)
    }
    return baseline_days, evaluation_days


def _daily_rows(scan: DailyScan, baseline_days: set[str]) -> list[dict]:
    rows = []
    for day, stats in sorted(scan.stats.items()):
        row = finalize_entity("date_local", day, stats)
        row["baseline_included"] = day in baseline_days
        rows.append(row)
    return rows


def _update_training(aggregation: TrainingAggregation, row: dict, local_time: datetime) -> None:
    weight = read_weight(row)
    event_class = row["event_class"] if row["event_class"] in EVENT_CLASSES else "other"
    user_key = row["user_key"]
    client_ip_key = row["client_ip_key"]
    relying_party = row["relying_party"] or "(sin_relying_party)"
    aggregation.event_count += weight
    aggregation.class_totals[event_class] += weight
    if user_key:
        aggregation.distinct_users.add(user_key)
    if client_ip_key:
        aggregation.distinct_ips.add(client_ip_key)

    day_key = local_time.date().isoformat()
    aggregation.hourly_by_day[(day_key, local_time.hour)][event_class] += weight
    if user_key:
        update_entity(
            aggregation.user_stats[user_key],
            event_class,
            weight,
            local_time,
            user_key,
            client_ip_key,
            relying_party,
        )
        aggregation.user_hour_stats[(user_key, local_time.hour)][event_class] += weight
    if client_ip_key:
        update_entity(
            aggregation.ip_stats[client_ip_key],
            event_class,
            weight,
            local_time,
            user_key,
            client_ip_key,
            relying_party,
        )
    update_entity(
        aggregation.app_stats[relying_party],
        event_class,
        weight,
        local_time,
        user_key,
        client_ip_key,
        relying_party,
    )
    if user_key and client_ip_key:
        update_entity(
            aggregation.user_ip_stats[(user_key, client_ip_key)],
            event_class,
            weight,
            local_time,
            user_key,
            client_ip_key,
            relying_party,
        )
    if user_key and relying_party:
        update_entity(
            aggregation.user_app_stats[(user_key, relying_party)],
            event_class,
            weight,
            local_time,
            user_key,
            client_ip_key,
            relying_party,
        )


def _aggregate_training(
    input_csv: Path, local_timezone: ZoneInfo, baseline_days: set[str]
) -> TrainingAggregation:
    aggregation = TrainingAggregation()
    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            event_time = parse_timestamp(row["event_time_utc"])
            if event_time is None:
                continue
            local_time = event_time.astimezone(local_timezone)
            if local_time.date().isoformat() in baseline_days:
                _update_training(aggregation, row, local_time)
    return aggregation


def _hourly_rows(
    aggregation: TrainingAggregation, baseline_days: set[str]
) -> tuple[list[dict], set[int]]:
    rows = []
    observed_hours: set[int] = set()
    for hour in range(24):
        day_totals = []
        combined = class_counter()
        for day in sorted(baseline_days):
            counts = aggregation.hourly_by_day[(day, hour)]
            combined.update(counts)
            day_totals.append(sum(counts.values()))
        total = sum(day_totals)
        days_with_data = sum(value > 0 for value in day_totals)
        if days_with_data:
            observed_hours.add(hour)
        success, failure, lockout = (
            combined["success"],
            combined["failure"],
            combined["lockout"],
        )
        rows.append(
            {
                "hour_local": hour,
                "days_observed": len(baseline_days),
                "days_with_data": days_with_data,
                "coverage_status": "observed" if days_with_data else "unobserved",
                "total_events": total,
                "average_events_per_day": round(total / len(baseline_days), 2),
                "median_events_per_day": median(day_totals),
                "p95_events_per_day": percentile(day_totals, 0.95),
                "success_count": success,
                "failure_count": failure,
                "lockout_count": lockout,
                "failure_rate": rate(failure, success + failure),
                "adverse_event_rate": rate(failure + lockout, total),
            }
        )
    return rows, observed_hours


def _relationship_rows(
    stats_by_pair: dict[tuple[str, str], dict], identifier_name: str, user_totals: dict[str, int]
) -> list[dict]:
    rows = []
    for (user_key, identifier), stats in stats_by_pair.items():
        row = {"user_key": user_key, **finalize_entity(identifier_name, identifier, stats)}
        row["share_of_user_events"] = rate(row["total_events"], user_totals[user_key])
        rows.append(row)
    rows.sort(key=lambda row: (row["user_key"], -row["total_events"]))
    return rows


def _profile_rows(aggregation: TrainingAggregation, minimum_history: int) -> ProfileRows:
    users = [
        finalize_entity("user_key", key, stats) for key, stats in aggregation.user_stats.items()
    ]
    for row in users:
        row["history_status"] = (
            "sufficient" if row["total_events"] >= minimum_history else "insufficient"
        )
    users.sort(
        key=lambda row: (row["failure_count"] + row["lockout_count"], row["total_events"]),
        reverse=True,
    )
    ips = [
        finalize_entity("client_ip_key", key, stats) for key, stats in aggregation.ip_stats.items()
    ]
    ips.sort(
        key=lambda row: (row["failure_count"] + row["lockout_count"], row["distinct_users"]),
        reverse=True,
    )
    apps = [
        finalize_entity("relying_party", key, stats) for key, stats in aggregation.app_stats.items()
    ]
    apps.sort(key=lambda row: row["total_events"], reverse=True)

    user_totals = {row["user_key"]: row["total_events"] for row in users}
    user_hours = []
    for (user_key, hour), counts in aggregation.user_hour_stats.items():
        total = sum(counts.values())
        user_hours.append(
            {
                "user_key": user_key,
                "hour_local": hour,
                "event_count": total,
                "share_of_user_events": rate(total, user_totals[user_key]),
                "success_count": counts["success"],
                "failure_count": counts["failure"],
                "lockout_count": counts["lockout"],
            }
        )
    user_hours.sort(key=lambda row: (row["user_key"], row["hour_local"]))
    return ProfileRows(
        users,
        ips,
        apps,
        user_hours,
        _relationship_rows(aggregation.user_ip_stats, "client_ip_key", user_totals),
        _relationship_rows(aggregation.user_app_stats, "relying_party", user_totals),
    )


def _write_artifacts(
    output_dir: Path, daily_rows: list[dict], hourly_rows: list[dict], profiles: ProfileRows
) -> None:
    write_csv(output_dir / "daily_activity.csv", daily_rows)
    write_csv(output_dir / "hourly_activity.csv", hourly_rows)
    write_csv(output_dir / "user_behavior.csv", profiles.users)
    write_csv(output_dir / "ip_behavior.csv", profiles.ips)
    write_csv(output_dir / "relying_party_behavior.csv", profiles.apps)
    write_csv(output_dir / "user_hour_profile.csv", profiles.user_hours)
    write_csv(output_dir / "user_ip_profile.csv", profiles.user_ips)
    write_csv(output_dir / "user_app_profile.csv", profiles.user_apps)


def _distribution_summary(profiles: ProfileRows) -> dict:
    user_failures = [int(row["failure_count"]) for row in profiles.users]
    ip_failures = [int(row["failure_count"]) for row in profiles.ips]
    ip_user_counts = [int(row["distinct_users"]) for row in profiles.ips]
    return {
        "failure_events_per_user": {
            "p50": percentile(user_failures, 0.50),
            "p95": percentile(user_failures, 0.95),
            "p99": percentile(user_failures, 0.99),
            "maximum": max(user_failures, default=0),
        },
        "failure_events_per_ip": {
            "p50": percentile(ip_failures, 0.50),
            "p95": percentile(ip_failures, 0.95),
            "p99": percentile(ip_failures, 0.99),
            "maximum": max(ip_failures, default=0),
        },
        "distinct_users_per_ip": {
            "p50": percentile(ip_user_counts, 0.50),
            "p95": percentile(ip_user_counts, 0.95),
            "p99": percentile(ip_user_counts, 0.99),
            "maximum": max(ip_user_counts, default=0),
        },
    }


def _build_summary(
    *,
    input_csv: Path,
    config: dict,
    scan: DailyScan,
    baseline_days: set[str],
    evaluation_days: set[str],
    aggregation: TrainingAggregation,
    profiles: ProfileRows,
    observed_hours: set[int],
) -> dict:
    minimum_history = int(config.get("minimum_user_history_events", 20))
    training_start = str(config.get("training_start_local", ""))
    training_end = str(config.get("training_end_local", ""))
    evaluation_start = str(config.get("evaluation_start_local", ""))
    return {
        "source_file": str(input_csv),
        "timezone": config["timezone"],
        "input_rows": scan.input_rows,
        "valid_time_rows": scan.input_rows - scan.invalid_time_rows,
        "invalid_time_rows": scan.invalid_time_rows,
        "observed_days": sorted(scan.stats),
        "baseline_days": sorted(baseline_days),
        "baseline_day_count": len(baseline_days),
        "baseline_event_count": aggregation.event_count,
        "baseline_distinct_users": len(aggregation.distinct_users),
        "baseline_distinct_client_ips": len(aggregation.distinct_ips),
        "evaluation_days": sorted(evaluation_days),
        "evaluation_event_count": sum(scan.stats[day]["total"] for day in evaluation_days),
        "baseline_event_classes": dict(aggregation.class_totals),
        "baseline_failure_rate": rate(
            aggregation.class_totals["failure"],
            aggregation.class_totals["success"] + aggregation.class_totals["failure"],
        ),
        "users_with_sufficient_history": sum(
            row["history_status"] == "sufficient" for row in profiles.users
        ),
        "users_with_insufficient_history": sum(
            row["history_status"] == "insufficient" for row in profiles.users
        ),
        "observed_local_hours": sorted(observed_hours),
        "unobserved_local_hours": [hour for hour in range(24) if hour not in observed_hours],
        "completeness_criteria": {
            "minimum_events_per_day": int(config["minimum_events_per_day"]),
            "minimum_active_hours_per_day": int(config["minimum_active_hours_per_day"]),
            "minimum_user_history_events": minimum_history,
        },
        "training_period": {
            "start_local": training_start or min(baseline_days),
            "end_local": training_end or max(baseline_days),
            "future_events_excluded": True,
        },
        "evaluation_period": {
            "start_local": evaluation_start or min(evaluation_days, default=""),
            "end_local": max(evaluation_days, default=""),
            "days_with_events": len(evaluation_days),
        },
        "distributions": _distribution_summary(profiles),
    }


def run_baseline(input_csv: Path, output_dir: Path, config: dict) -> dict:
    local_timezone = ZoneInfo(config["timezone"])
    scan = _scan_daily(input_csv, local_timezone)
    baseline_days, evaluation_days = _select_period_days(scan, config)
    aggregation = _aggregate_training(input_csv, local_timezone, baseline_days)
    hourly_rows, observed_hours = _hourly_rows(aggregation, baseline_days)
    profiles = _profile_rows(aggregation, int(config.get("minimum_user_history_events", 20)))
    _write_artifacts(output_dir, _daily_rows(scan, baseline_days), hourly_rows, profiles)
    summary = _build_summary(
        input_csv=input_csv,
        config=config,
        scan=scan,
        baseline_days=baseline_days,
        evaluation_days=evaluation_days,
        aggregation=aggregation,
        profiles=profiles,
        observed_hours=observed_hours,
    )
    (output_dir / "baseline_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/baseline.json"))
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    summary = run_baseline(args.input_csv, args.output_dir, config)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
