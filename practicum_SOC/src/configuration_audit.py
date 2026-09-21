"""Detecta cambios de configuración desplegada sin copiar valores sensibles al historial."""

import hashlib
import json

from alert_store import utc_now
from auth_store import AuthStore

CONFIG_FILES = ("auth.json", "detection_rules.json", "operational.json")


def observe_configuration(store, directory, policy):
    actor = {"user_id": "system:deployment", "display_name": "Observador de configuración"}
    with store.connection:
        store.connection.execute(
            "UPDATE platform_auth_guard SET revision = revision + 1 WHERE singleton = 1"
        )
        for filename in CONFIG_FILES:
            payload = json.loads((directory / filename).read_text(encoding="utf-8"))
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            digest = hashlib.sha256(canonical.encode()).hexdigest()
            previous = store.connection.execute(
                "SELECT content_hash FROM platform_config_observations WHERE filename = ?",
                (filename,),
            ).fetchone()
            if previous and previous["content_hash"] == digest:
                continue
            AuthStore(store, policy).audit(
                actor,
                "configuration_change_detected" if previous else "configuration_baseline",
                filename,
                {
                    "previous_sha256": previous["content_hash"] if previous else None,
                    "current_sha256": digest,
                    "change_author": "unknown_external",
                },
            )
            store.connection.execute(
                "INSERT INTO platform_config_observations VALUES (?, ?, ?) "
                "ON CONFLICT(filename) DO UPDATE SET content_hash = excluded.content_hash, "
                "observed_at_utc = excluded.observed_at_utc",
                (filename, digest, utc_now()),
            )
    return [
        dict(row)
        for row in store.connection.execute(
            "SELECT * FROM platform_config_observations ORDER BY filename"
        ).fetchall()
    ]
