"""Consultas acotadas y cola persistente compartida por SQLite y PostgreSQL."""

import ipaddress
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from practicum_soc.core.private_ip import decrypt_payload, encrypt_payload
from practicum_soc.repositories.alerts import utc_now


class InvestigationQueueFull(ValueError):
    pass


def encrypted_ip_rows(event_values, original_ips):
    if original_ips is None:
        return []
    if len(event_values) != len(original_ips):
        raise ValueError("El lote de IP no corresponde al lote de eventos")
    result = []
    for event, address in zip(event_values, original_ips, strict=True):
        if address and event[12]:
            address = ipaddress.ip_address(address).compressed
            result.append(
                (event[0], event[1], event[8], encrypt_payload({"ip": address}), utc_now())
            )
    return result


class InvestigationRepository:
    def __init__(self, store):
        self.store, self.db = store, store.connection

    def get(self, analysis_id):
        row = self.db.execute(
            "SELECT * FROM alert_investigations WHERE analysis_id=?", (analysis_id,)
        ).fetchone()
        return dict(row) if row else None

    def enqueue(self, alert_id, actor_id, policy, *, force_new=False):
        cutoff = (datetime.now(UTC) - timedelta(minutes=policy.reuse_minutes)).isoformat()
        with self.db:
            # Un bloqueo de fila en PG y la transacción de escritura SQLite serializan decisiones.
            self.db.execute("UPDATE investigation_guard SET revision=revision+1 WHERE singleton=1")
            active = self.db.execute(
                "SELECT analysis_id FROM alert_investigations WHERE alert_id=? "
                "AND status IN ('pending','in_progress') LIMIT 1",
                (alert_id,),
            ).fetchone()
            if active:
                return self.get(active["analysis_id"]), True
            if not force_new:
                recent = self.db.execute(
                    "SELECT analysis_id FROM alert_investigations WHERE alert_id=? "
                    "AND status='completed' AND finished_at_utc>=? "
                    "ORDER BY finished_at_utc DESC LIMIT 1",
                    (alert_id, cutoff),
                ).fetchone()
                if recent:
                    return self.get(recent["analysis_id"]), True
            pending = self.db.execute(
                "SELECT COUNT(*) AS n FROM alert_investigations WHERE status='pending'"
            ).fetchone()["n"]
            if pending >= policy.maximum_pending_jobs:
                raise InvestigationQueueFull(
                    "La cola está llena; espere antes de solicitar análisis"
                )
            identifier = uuid4().hex
            self.db.execute(
                "INSERT INTO alert_investigations "
                "(analysis_id,alert_id,status,requested_by,created_at_utc,policy_json) "
                "VALUES (?,?,'pending',?,?,?)",
                (identifier, alert_id, actor_id, utc_now(), policy.model_dump_json()),
            )
        return self.get(identifier), False

    def claim(self, policy):
        now = int(time.time())
        with self.db:
            self.db.execute("UPDATE investigation_guard SET revision=revision+1 WHERE singleton=1")
            # No se reenvía a una IA tras un crash: pudo facturar sin llegar a guardar respuesta.
            self.db.execute(
                "UPDATE alert_investigations SET status='failed',error_code='worker_interrupted',"
                "finished_at_utc=?,lease_until=NULL WHERE status='in_progress' AND lease_until<=?",
                (utc_now(), now),
            )
            active = self.db.execute(
                "SELECT COUNT(*) AS n FROM alert_investigations WHERE status='in_progress'"
            ).fetchone()["n"]
            if active >= policy.maximum_concurrent_jobs:
                return None
            row = self.db.execute(
                "SELECT analysis_id,policy_json FROM alert_investigations WHERE status='pending' "
                "ORDER BY created_at_utc,analysis_id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            lease = json.loads(row["policy_json"])["lease_seconds"]
            self.db.execute(
                "UPDATE alert_investigations SET status='in_progress',started_at_utc=?,lease_until=? "
                "WHERE analysis_id=? AND status='pending'",
                (utc_now(), now + lease, row["analysis_id"]),
            )
        return self.get(row["analysis_id"])

    def finish(self, job, result=None, error_code=None):
        # Una respuesta tardía no sobreescribe un trabajo que otro worker ya recuperó como fallido.
        with self.db:
            self.db.execute(
                "UPDATE alert_investigations SET status=?,result_ciphertext=?,error_code=?,"
                "finished_at_utc=?,lease_until=NULL WHERE analysis_id=? AND status='in_progress' "
                "AND lease_until=?",
                (
                    "failed" if error_code else "completed",
                    encrypt_payload(result) if result else None,
                    error_code,
                    utc_now(),
                    job["analysis_id"],
                    job["lease_until"],
                ),
            )

    def events(self, source, field, value, start, end, limit):
        if field not in {"user_key", "client_ip_key"}:
            raise ValueError("Entidad no admitida")
        if not value:
            return []
        rows = self.db.execute(
            "SELECT source_event_id,event_time_utc,event_class,event_count,user_key,client_ip_key,"
            "relying_party FROM normalized_events WHERE source_name=? AND is_consistent=1 "
            f"AND {field}=? AND event_time_utc>=? AND event_time_utc<=? "
            "ORDER BY event_time_utc DESC,source_event_id LIMIT ?",
            (source, value, start, end, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def counts(self, source, field, value, start, end):
        if field not in {"user_key", "client_ip_key"}:
            raise ValueError("Entidad no admitida")
        if not value:
            return None
        row = self.db.execute(
            "SELECT COUNT(*) AS records,COALESCE(SUM(event_count),0) AS events,"
            "COALESCE(SUM(CASE WHEN event_class='failure' THEN event_count ELSE 0 END),0) AS failures,"
            "COALESCE(SUM(CASE WHEN event_class='success' THEN event_count ELSE 0 END),0) AS successes,"
            "COALESCE(SUM(CASE WHEN event_class='lockout' THEN event_count ELSE 0 END),0) AS lockouts,"
            "COUNT(DISTINCT NULLIF(user_key,'')) AS distinct_users "
            "FROM normalized_events WHERE source_name=? AND is_consistent=1 "
            f"AND {field}=? AND event_time_utc>=? AND event_time_utc<=?",
            (source, value, start, end),
        ).fetchone()
        return dict(row)

    def evidence_events(self, alert, limit):
        identities = str(alert.get("evidence_event_ids") or "").split(";")[:limit]
        source = alert["source_name"]
        candidates = sorted(
            {
                candidate
                for identity in identities
                if identity
                for candidate in (identity, f"{source}:{identity}", f"{source}:event:{identity}")
            }
        )
        if not candidates:
            return []
        placeholders = ",".join("?" for _ in candidates)
        rows = self.db.execute(
            "SELECT source_event_id,event_time_utc,event_class,event_count,user_key,client_ip_key,"
            "relying_party FROM normalized_events WHERE source_name=? AND is_consistent=1 "
            f"AND source_event_id IN ({placeholders}) ORDER BY event_time_utc LIMIT ?",
            (source, *candidates, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def original_ips(self, source, keys):
        addresses, unavailable = [], []
        for key in sorted(set(keys)):
            rows = self.db.execute(
                "SELECT DISTINCT encrypted_ip FROM investigation_private_ips "
                "WHERE source_name=? AND client_ip_key=? ORDER BY encrypted_ip LIMIT 2",
                (source, key),
            ).fetchall()
            if not rows:
                unavailable.append("La IP original no fue conservada; el HMAC no es reversible")
            for row in rows:
                try:
                    address = ipaddress.ip_address(decrypt_payload(row["encrypted_ip"])["ip"])
                    addresses.append(address.compressed)
                except (ValueError, KeyError):
                    unavailable.append(
                        "No se pudo leer la IP con la clave de investigación configurada"
                    )
        return sorted(set(addresses)), sorted(set(unavailable))
