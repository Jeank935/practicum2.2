"""Ingesta histórica y evaluación con el motor existente, sin mover el cursor live."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from practicum_soc.core.private_ip import capture_original_ip
from practicum_soc.integrations.notifications import SocInboxProvider, deliver_once
from practicum_soc.repositories.rules import RULE_FIELDS, RuleConfigStore
from practicum_soc.services.monitoring import cooldown_for_alert, event_from_row, load_exclusions
from practicum_soc.soc.detection import detect_alerts, evaluation_events, load_baseline_context
from practicum_soc.soc.normalization import normalize_record, rejection_reasons


def ingest_range(source, store, start, end, lookback, secret, normalization, policy, progress):
    stats = {"fetched": 0, "inserted": 0, "duplicates": 0, "rejected": 0}
    reasons = Counter()
    for number, records in enumerate(
        source.batches(start - timedelta(minutes=lookback), end, policy["batch_size"]), 1
    ):
        items = []
        original_ips = []
        for record in records:
            event = normalize_record(record.values, secret, normalization.minimum_year)
            rejected = rejection_reasons(event, normalization)
            reasons.update(rejected)
            stats["rejected"] += bool(rejected)
            items.append((event, record.cursor.timestamp_utc, record.cursor.event_id, not rejected))
            original_ips.append(capture_original_ip(record.values, event, secret))
        inserted = store.insert_events(items, source.source_name, original_ips=original_ips)
        stats["fetched"] += len(records)
        stats["inserted"] += inserted
        stats["duplicates"] += len(records) - inserted
        if number % policy["progress_every_batches"] == 0:
            progress({"stage": "ingestion", **stats})
    return {**stats, "rejection_reasons": dict(reasons)}


def read_history_events(store, source, start, end, lookback, timezone, batch_size):
    query = (
        "SELECT source_event_id,event_time_utc,event_class,user_key,client_ip_key,"
        "relying_party,event_count FROM normalized_events WHERE source_name=? "
        "AND is_consistent=1 AND event_time_utc>=? AND event_time_utc<? "
        "ORDER BY event_time_utc,source_event_id"
    )
    parameters = (
        source,
        (start - timedelta(minutes=lookback)).astimezone(UTC).isoformat(),
        end.astimezone(UTC).isoformat(),
    )
    if hasattr(store.connection, "iterate"):
        rows = store.connection.iterate(query, parameters, batch_size)
    else:
        rows = store.connection.execute(query, parameters)
    return [event for row in rows if (event := event_from_row(dict(row), timezone))]


def persist_candidates(store, candidates, config, source, version, start, end, max_attempts):
    results = Counter()
    provider = SocInboxProvider()
    # La persistencia del cooldown exige orden cronológico por final de la evidencia.
    for alert in sorted(candidates, key=lambda item: item["last_seen_local"]):
        occurred = datetime.fromisoformat(alert["last_seen_local"])
        if not start <= occurred < end:
            continue
        alert["rule_version_id"] = version
        created, reason = store.insert_alert(alert, cooldown_for_alert(alert, config), source)
        results[reason] += 1
        if created and alert["severity"] in {"high", "critical"}:
            deliver_once(store, provider, alert, max_attempts)
    return dict(results)


def verify_duplicates(store, source, start, end, limit):
    rows = store.connection.execute(
        "SELECT * FROM normalized_events WHERE source_name=? AND event_time_utc>=? "
        "AND event_time_utc<? ORDER BY event_time_utc LIMIT ?",
        (source, start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat(), limit),
    ).fetchall()
    items = []
    for row in rows:
        event = dict(row)
        event["deduplication_key"] = event["source_event_id"].split(":", 1)[1]
        items.append(
            (
                event,
                event["source_cursor_time_utc"],
                event["source_cursor_event_id"],
                bool(event["is_consistent"]),
            )
        )
    inserted = store.insert_events(items, source)
    if inserted:
        raise RuntimeError("La verificación de deduplicación insertó duplicados")
    return {"events_replayed": len(rows), "new_events_on_replay": inserted}


def analyze_history(
    *, source, store, start, end, secret, normalization, detection, operational, policy, progress
):
    checkpoint_before = store.get_checkpoint("postgresql_live")
    version = RuleConfigStore(store, detection).current()
    rules = version["config"]
    baseline = load_baseline_context(Path(operational["baseline_dir"]))
    if baseline.training_end_local and baseline.training_end_local >= start.date().isoformat():
        raise ValueError("La línea base debe ser anterior al periodo evaluado")
    exclusions = load_exclusions(Path(operational["exclusions_file"]))
    lookback = max(int(rules[key]["window_minutes"]) for key in RULE_FIELDS)
    run_id = store.start_run(source.source_name)
    ingestion = {}
    try:
        ingestion = ingest_range(
            source, store, start, end, lookback, secret, normalization, policy, progress
        )
        progress({"stage": "detection", **ingestion})
        events = evaluation_events(
            read_history_events(
                store,
                source.source_name,
                start,
                end,
                lookback,
                rules["timezone"],
                policy["batch_size"],
            ),
            baseline,
        )
        candidates = detect_alerts(events, rules, baseline, exclusions)
        persistence = persist_candidates(
            store,
            candidates,
            rules,
            source.source_name,
            version["version_id"],
            start,
            end,
            operational["notification_policy"]["maximum_delivery_attempts"],
        )
        verification = verify_duplicates(
            store, source.source_name, start, end, policy["verification_event_limit"]
        )
        unchanged = checkpoint_before == store.get_checkpoint("postgresql_live")
        if not unchanged:
            raise RuntimeError("El checkpoint live cambió durante el análisis histórico")
        store.finish_run(
            run_id,
            "completed",
            fetched_count=ingestion["fetched"],
            inserted_event_count=ingestion["inserted"],
            alert_count=persistence.get("created", 0),
        )
        return {
            "source": source.source_name,
            "from_local": start.isoformat(),
            "to_local_exclusive": end.isoformat(),
            "run_id": run_id,
            "rule_version_id": version["version_id"],
            "rule_config": rules,
            "baseline_training_end": baseline.training_end_local,
            "ingestion": ingestion,
            "valid_events_evaluated_with_context": len(events),
            "candidate_alerts": len(candidates),
            "persistence": persistence,
            "verification": {**verification, "live_checkpoint_unchanged": unchanged},
        }
    except Exception as error:
        store.finish_run(
            run_id,
            "failed",
            fetched_count=ingestion.get("fetched", 0),
            inserted_event_count=ingestion.get("inserted", 0),
            error_code=type(error).__name__,
        )
        raise
