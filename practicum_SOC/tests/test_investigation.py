"""IP, cuentas y proveedores simulados; ninguna prueba debe generar tráfico o gastos."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from test_alert_store import sample_alert
from test_auth import claims

from practicum_soc import main
from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.core.investigation_config import InvestigationSettings, InvestigationUnavailable
from practicum_soc.core.private_ip import capture_original_ip
from practicum_soc.integrations.ai_explanation import OpenAIExplanationClient
from practicum_soc.integrations.investigation_http import ProviderFailure
from practicum_soc.integrations.ip_reputation import IPReputationClient
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.auth import AuthStore
from practicum_soc.repositories.investigation import InvestigationRepository
from practicum_soc.schemas.investigation import AIExplanation
from practicum_soc.services.investigation import (
    InvestigationWorker,
    limited_context,
    request_investigation,
    retrieve_investigation,
    token_cost,
    validated_explanation,
)
from practicum_soc.services.investigation_context import baseline_comparison, collect_context
from practicum_soc.soc.normalization import pseudonymize

SOURCE = "postgresql_live"


@pytest.fixture
def policy(monkeypatch):
    for key, value in {
        "SOC_ENV": "local",
        "SOC_AUTH_MODE": "oidc",
        "SOC_STORAGE_BACKEND": "sqlite",
        "SOC_PUBLIC_URL": "http://127.0.0.1:8000",
        "SOC_OIDC_ISSUER": "http://127.0.0.1:8080/realms/soc",
        "SOC_OIDC_CLIENT_SECRET": "synthetic-client-secret",
        "SOC_AI_ENABLED": "true",
        "SOC_AI_MODEL": "synthetic-model",
        "OPENAI_API_KEY": "synthetic-not-real",
        "SOC_INVESTIGATION_IP_KEY": Fernet.generate_key().decode(),
        "SOC_INVESTIGATION_CAPTURE_IP": "false",
        "SOC_IP_REPUTATION_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    import practicum_soc.integrations.ai_explanation as ai_module
    import practicum_soc.integrations.ip_reputation as reputation_module

    def forbidden(*args, **kwargs):
        raise AssertionError("Consultas HTTP reales prohibidas en pruebas")

    monkeypatch.setattr(ai_module, "request_json", forbidden)
    monkeypatch.setattr(reputation_module, "request_json", forbidden)
    return InvestigationSettings.load()


@pytest.fixture
def database(tmp_path, policy):
    db = tmp_path / "investigation.db"
    with AlertStore(db) as store:
        auth = AuthStore(store, AuthSettings.from_env().policy)
        token = auth.login(claims())
        actor = auth.session(token)
    return db, token, actor


def seed(db, address="10.5.6.7", capture=True):
    alert = sample_alert()
    alert["client_ip_key"] = pseudonymize(address, b"synthetic-hmac", "ip")
    with AlertStore(db) as store:
        store.insert_alert(alert, source_name=SOURCE)
        for index, event_class in enumerate(
            ("failure", "failure", "failure", "success", "lockout")
        ):
            timestamp = f"2026-03-16T15:0{index}:00+00:00"
            event = {
                "source_event_id": str(index + 1),
                "event_time_utc": timestamp,
                "event_class": event_class,
                "event_count": index + 1 if index < 3 else 1,
                "user_key": "usr_test" if index < 4 else "usr_other",
                "client_ip_key": alert["client_ip_key"],
                "relying_party": "synthetic-app",
            }
            store.insert_event(
                event,
                timestamp,
                str(index + 1),
                True,
                source_name=SOURCE,
                original_ip=address if capture else None,
            )
    return alert


class FakeAI:
    def __init__(self, failure=None, invalid=False):
        self.contexts, self.failure, self.invalid = [], failure, invalid

    def explain(self, context, policy):
        self.contexts.append(context)
        if self.failure:
            raise self.failure
        if self.invalid:
            return {"summary": "Incompleta"}, {}
        reference = context["events"][0]["source_event_id"] if context["events"] else "alert"
        return AIExplanation(
            summary="Los fallos no confirman por sí solos un ataque.",
            evidence=[{"statement": "Eventos aportados", "references": [reference]}],
            interpretation="Requiere investigación humana.",
            legitimate_explanations=["Contraseña guardada desactualizada"],
            missing_information=["Confirmación del titular"],
            recommendations=["Confirmar el patrón con el responsable autorizado"],
        ), {"input_tokens": 120, "output_tokens": 70}


def enqueue(database, policy, force=False):
    with AlertStore(database[0]) as store:
        return request_investigation(store, "alt_1", database[2], policy, force_new=force)


def run(database, policy, tmp_path, ai=None, reputation=None):
    worker = InvestigationWorker(
        database[0],
        ai=ai or FakeAI(),
        reputation=reputation or Mock(),
        baseline_dir=tmp_path / "absent",
    )
    identifier = worker.run_once(policy)
    with AlertStore(database[0]) as store:
        return retrieve_investigation(store, "alt_1", identifier, database[2])


def test_real_private_ip_counts_evidence_and_no_side_effects(database, policy, tmp_path):
    alert = seed(database[0])
    job = enqueue(database, policy)
    ai, reputation = FakeAI(), Mock()
    result = run(database, policy, tmp_path, ai, reputation)
    assert job.status == "pending" and result.status == "completed"
    assert result.real_ip == result.result.real_ip == "10.5.6.7"
    context = result.result.context
    assert context["user_counts"]["failures"] == 6 and context["user_counts"]["successes"] == 1
    assert context["ip_counts"][alert["client_ip_key"]]["distinct_users"] == 2
    assert context["success_after_failure_event_ids"] == [SOURCE + ":4"]
    assert context["other_affected_user_keys"] == ["usr_other"]
    assert result.result.reputation[0].status == "not_applicable"
    reputation.check.assert_not_called()
    assert "real_ips" not in ai.contexts[0]
    assert result.result.usage["estimated_cost_usd"] is None
    with AlertStore(database[0]) as store:
        current = store.get_alert("alt_1")
        assert current["risk_score"] == 75 and current["severity"] == "high"
        assert current["investigation_status"] == "new"
        encrypted = store.connection.execute(
            "SELECT encrypted_ip FROM investigation_private_ips"
        ).fetchone()[0]
        saved = InvestigationRepository(store).get(result.analysis_id)
        assert "10.5.6.7" not in encrypted + saved["result_ciphertext"]


def test_historical_hmac_and_missing_baseline(database, policy, tmp_path):
    seed(database[0], capture=False)
    enqueue(database, policy)
    result = run(database, policy, tmp_path)
    assert result.status == "completed" and result.real_ip is None
    assert "HMAC" in result.real_ip_unavailable_reason
    assert not result.result.context["baseline"]["available"]


def test_missing_events_are_explicit(database, policy, tmp_path):
    with AlertStore(database[0]) as store:
        store.insert_alert(sample_alert(), source_name=SOURCE)
    enqueue(database, policy)
    result = run(database, policy, tmp_path)
    assert result.status == "completed" and result.result.context["events"] == []
    assert result.result.context["missing_information"]


def test_external_reputation_outage_is_not_fatal(database, policy, tmp_path):
    seed(database[0], "8.8.8.8")  # IP del escenario simulado: no se consulta realmente.
    enqueue(database, policy)
    reputation = Mock()
    reputation.check.side_effect = ProviderFailure("simulated-outage")
    result = run(database, policy, tmp_path, reputation=reputation)
    assert result.status == "completed" and result.real_ip == "8.8.8.8"
    assert result.result.reputation[0].status == "unavailable"


@pytest.mark.parametrize("invalid", [False, True])
def test_failed_or_invalid_ai_is_controlled(database, policy, tmp_path, invalid):
    seed(database[0])
    enqueue(database, policy)
    ai = (
        FakeAI(invalid=True) if invalid else FakeAI(failure=ProviderFailure("provider_unavailable"))
    )
    result = run(database, policy, tmp_path, ai=ai)
    assert result.status == "failed" and result.result is None and result.error_code
    assert "synthetic-not-real" not in result.model_dump_json()


def test_active_duplicates_recent_reuse_and_force(database, policy, tmp_path):
    seed(database[0])
    first = enqueue(database, policy)
    assert enqueue(database, policy, True).analysis_id == first.analysis_id
    run(database, policy, tmp_path)
    recent = enqueue(database, policy)
    assert recent.reused and recent.status == "completed"
    forced = enqueue(database, policy, True)
    assert not forced.reused and forced.analysis_id != first.analysis_id


def test_atomic_duplicates_and_global_concurrency(database, policy):
    seed(database[0])

    def submit(_):
        with AlertStore(database[0]) as store:
            return request_investigation(store, "alt_1", database[2], policy).analysis_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(submit, range(8)))
    assert len(set(identities)) == 1
    with AlertStore(database[0]) as store:
        repo = InvestigationRepository(store)
        assert repo.claim(policy)["status"] == "in_progress" and repo.claim(policy) is None


def test_crashed_job_not_rebilled_and_pending_survives_restart(database, policy):
    seed(database[0])
    job = enqueue(database, policy)
    with AlertStore(database[0]) as store:
        repo = InvestigationRepository(store)
        claimed = repo.claim(policy)
        with store.connection:
            store.connection.execute(
                "UPDATE alert_investigations SET lease_until=? WHERE analysis_id=?",
                (int(time.time()) - 1, job.analysis_id),
            )
    with AlertStore(database[0]) as store:
        repo = InvestigationRepository(store)
        assert repo.claim(policy) is None
        assert repo.get(job.analysis_id)["error_code"] == "worker_interrupted"
        repo.finish(claimed, {"late": "must-not-be-saved"})
        assert repo.get(job.analysis_id)["status"] == "failed"
    assert enqueue(database, policy, True).status == "pending"


def test_requester_revoked_does_not_call_ai(database, policy):
    seed(database[0])
    enqueue(database, policy)
    ai = FakeAI()
    with AlertStore(database[0]) as store:
        with store.connection:
            store.connection.execute(
                "UPDATE platform_users SET enabled=0 WHERE user_id=?", (database[2]["user_id"],)
            )
    identifier = InvestigationWorker(database[0], ai=ai).run_once(policy)
    assert ai.contexts == []
    with AlertStore(database[0]) as store:
        assert (
            InvestigationRepository(store).get(identifier)["error_code"]
            == "requester_access_revoked"
        )


def test_capture_matches_hmac_and_uses_client_not_server(policy, monkeypatch):
    monkeypatch.setenv("SOC_INVESTIGATION_CAPTURE_IP", "true")
    raw = "2001:0db8:0000:0000:0000:0000:0000:0001"
    normalized = {"client_ip_key": pseudonymize("2001:db8::1", b"key", "ip")}
    assert (
        capture_original_ip({"custom_ip_address": raw, "source_ip": "10.0.0.5"}, normalized, b"key")
        == "2001:db8::1"
    )
    assert capture_original_ip({"custom_ip_address": "invalid"}, normalized, b"key") is None
    assert capture_original_ip({"custom_ip_address": raw}, normalized, b"wrong") is None


def test_api_permissions_csrf_missing_alert_fast_response(database, policy, monkeypatch, tmp_path):
    seed(database[0])
    app = main.create_app()
    app.state.soc_state_db = database[0]
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    url = "/api/v1/alerts/alt_1/investigations"
    assert client.post(url, json={}).status_code == 401
    assert client.get(url + "/missing").status_code == 401
    client.cookies.set("soc_session", database[1])
    assert client.post(url, json={}).status_code == 403
    headers = {"X-CSRF-Token": database[2]["csrf_token"]}
    assert (
        client.post("/api/v1/alerts/missing/investigations", json={}, headers=headers).status_code
        == 404
    )
    response = client.post(url, json={}, headers=headers)
    assert response.status_code == 202 and response.json()["status"] == "pending"
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get(response.headers["Location"]).status_code == 200
    run(database, policy, tmp_path)
    completed = client.get(response.headers["Location"])
    assert completed.json()["real_ip"] == "10.5.6.7"
    assert completed.headers["Cache-Control"] == "no-store"
    identifier = response.json()["analysis_id"]
    assert client.get("/api/v1/alerts/other/investigations/" + identifier).status_code == 404
    monkeypatch.setenv("SOC_AI_ENABLED", "false")
    assert client.post(url, json={}, headers=headers).status_code == 503
    monkeypatch.setenv("SOC_AI_PROVIDER", "unsupported")
    invalid_config = client.post(url, json={}, headers=headers)
    assert invalid_config.status_code == 503
    assert "inválida" in invalid_config.text


def test_forbidden_role_and_missing_credentials(database, policy, monkeypatch):
    seed(database[0])
    with AlertStore(database[0]) as store:
        with pytest.raises(PermissionError):
            request_investigation(store, "alt_1", {"role": "consultation", "enabled": 1}, policy)
        monkeypatch.delenv("OPENAI_API_KEY")
        with pytest.raises(InvestigationUnavailable, match="OPENAI_API_KEY"):
            request_investigation(store, "alt_1", database[2], policy)


def test_reputation_public_only_validates_ip_and_schema(policy, monkeypatch):
    import practicum_soc.integrations.ip_reputation as module

    client = IPReputationClient()
    for address in ("192.168.1.1", "127.0.0.1", "203.0.113.1", "224.0.0.1", "ff02::1", "fec0::1"):
        assert client.check(address, policy).status == "not_applicable"
    assert client.check("8.8.8.8", policy).status == "disabled"
    monkeypatch.setenv("SOC_IP_REPUTATION_ENABLED", "true")
    monkeypatch.delenv("ABUSEIPDB_API_KEY", raising=False)
    assert client.check("8.8.8.8", policy).status == "unavailable"
    monkeypatch.setenv("ABUSEIPDB_API_KEY", "synthetic-key")
    monkeypatch.setattr(
        module,
        "request_json",
        lambda *a, **kw: {
            "data": {"ipAddress": "8.8.8.8", "abuseConfidenceScore": 14, "totalReports": 2}
        },
    )
    assert client.check("8.8.8.8", policy).total_reports == 2
    monkeypatch.setattr(module, "request_json", lambda *a, **kw: {"data": {"ipAddress": "1.1.1.1"}})
    assert client.check("8.8.8.8", policy).status == "unavailable"


def test_openai_contract_structured_no_tools_no_storage(policy, monkeypatch):
    import practicum_soc.integrations.ai_explanation as module

    explanation, _ = FakeAI().explain({"events": []}, policy)
    requests = []

    def response(url, headers, **kwargs):
        requests.append(kwargs["payload"])
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": explanation.model_dump_json()}],
                }
            ],
            "usage": {"input_tokens": 120, "output_tokens": 70},
        }

    monkeypatch.setattr(module, "request_json", response)
    result, usage = OpenAIExplanationClient().explain({"events": []}, policy)
    assert result.summary and usage["input_tokens"] == 120
    assert requests[0]["store"] is False and "tools" not in requests[0]
    assert requests[0]["text"]["format"]["strict"] is True
    assert "NO CONFIABLES" in requests[0]["instructions"]
    monkeypatch.setattr(module, "request_json", lambda *a, **kw: {"status": "incomplete"})
    with pytest.raises(ProviderFailure):
        OpenAIExplanationClient().explain({}, policy)


def test_opt_in_ai_ip_and_configured_cost(database, policy, tmp_path):
    seed(database[0])
    policy = policy.model_copy(
        update={
            "send_real_ip_to_ai": True,
            "input_usd_per_million_tokens": 1.0,
            "output_usd_per_million_tokens": 2.0,
        }
    )
    enqueue(database, policy)
    ai = FakeAI()
    result = run(database, policy, tmp_path, ai=ai)
    assert ai.contexts[0]["real_ips"] == ["10.5.6.7"]
    assert result.result.usage["estimated_cost_usd"] == "0.00026000"


def test_baseline_used_only_when_prior_and_sufficient(database, policy, tmp_path, monkeypatch):
    import practicum_soc.services.investigation_context as module
    from practicum_soc.soc.detection import BaselineContext

    alert = seed(database[0])
    ip_key = alert["client_ip_key"]
    baseline = BaselineContext(
        sufficient_users=frozenset({"usr_test"}),
        known_user_ips=frozenset({("usr_test", ip_key)}),
        known_user_apps=frozenset(),
        known_user_hours=frozenset(),
        global_failure_rate=0.12,
        training_end_local="2026-03-15",
    )
    monkeypatch.setattr(module, "load_baseline_context", lambda _: baseline)
    comparison = baseline_comparison(tmp_path, alert, [ip_key, "ip_new"])
    assert comparison["available"] and comparison["sufficient_user_history"]
    assert comparison["known_user_ips"] == {ip_key: True, "ip_new": False}
    assert comparison["global_failure_rate"] == 0.12
    assert (
        baseline_comparison(tmp_path, {**alert, "user_key": "usr_unknown"}, [ip_key])[
            "known_user_ips"
        ]
        is None
    )
    assert not baseline_comparison(
        tmp_path, {**alert, "first_seen_local": "2026-03-14T10:00:00-05:00"}, [ip_key]
    )["available"]
    enqueue(database, policy)
    worker = InvestigationWorker(database[0], ai=FakeAI(), baseline_dir=tmp_path)
    analysis_id = worker.run_once(policy)
    with AlertStore(database[0]) as store:
        result = retrieve_investigation(store, "alt_1", analysis_id, database[2])
    assert result.result.context["baseline"]["known_user_ips"][ip_key]


def test_source_isolation_evidence_bounds_and_missing_ip(database, policy, tmp_path):
    alert = seed(database[0], capture=False)
    with AlertStore(database[0]) as store:
        event = {
            "source_event_id": "outside",
            "event_time_utc": "2026-03-16T15:00:00+00:00",
            "event_class": "failure",
            "event_count": 999,
            "user_key": "usr_test",
            "client_ip_key": alert["client_ip_key"],
        }
        store.insert_event(
            event, event["event_time_utc"], "outside", True, "other-source", original_ip="10.9.9.9"
        )
        limited = policy.model_copy(update={"maximum_events": 2})
        context, real_ip, addresses, _ = collect_context(
            store, store.get_alert("alt_1"), limited, tmp_path
        )
        assert len(context["events"]) == 2
        assert context["user_counts"]["failures"] == 6
        assert real_ip is None and addresses == []
        assert all(row["source_event_id"].startswith(SOURCE + ":") for row in context["events"])
        assert any("truncada" in note for note in context["missing_information"])


def test_ai_cannot_reference_invented_events(policy):
    explanation, _ = FakeAI().explain({"events": []}, policy)
    invalid = explanation.model_dump()
    invalid["evidence"] = [{"statement": "Supuesto", "references": ["invented-event"]}]
    with pytest.raises(ProviderFailure, match="ai_unknown_evidence"):
        validated_explanation(invalid, {"events": []})


def test_context_bound_and_unknown_usage_not_zero(database, policy, tmp_path):
    seed(database[0])
    with AlertStore(database[0]) as store:
        context, _, addresses, _ = collect_context(
            store, store.get_alert("alt_1"), policy, tmp_path
        )
    context["events"] *= 120
    limit = policy.model_copy(update={"maximum_context_bytes": 8192})
    trimmed = limited_context(context, [], addresses, limit)
    assert len(json.dumps(trimmed, ensure_ascii=False).encode()) <= 8192
    assert len(trimmed["events"]) < len(context["events"])
    with pytest.raises(ProviderFailure, match="context_limit"):
        limited_context({**context, "events": [], "extra": "x" * 20000}, [], [], limit)
    prices = policy.model_copy(
        update={"input_usd_per_million_tokens": 1, "output_usd_per_million_tokens": 2}
    )
    usage = token_cost({}, prices)
    assert usage["input_tokens"] is None and usage["estimated_cost_usd"] is None
    with pytest.raises(ProviderFailure, match="ai_invalid_usage"):
        token_cost({"input_tokens": -1}, prices)


def test_queue_capacity_and_invalid_configuration(database, policy):
    from pydantic import ValidationError

    from practicum_soc.repositories.investigation import InvestigationQueueFull

    seed(database[0])
    with AlertStore(database[0]) as store:
        store.insert_alert(sample_alert("alt_second"), source_name=SOURCE)
        limited = policy.model_copy(update={"maximum_pending_jobs": 1})
        request_investigation(store, "alt_1", database[2], limited)
        with pytest.raises(InvestigationQueueFull):
            request_investigation(store, "alt_second", database[2], limited)
    for changes in ({"maximum_events": 1001}, {"lease_seconds": 60}, {"provider": "unknown"}):
        with pytest.raises(ValidationError):
            policy.model_copy(update=changes).validated()


def test_direct_http_limits_invalid_json_and_no_redirects(policy, monkeypatch):
    from urllib.error import HTTPError

    import practicum_soc.integrations.investigation_http as module

    class Response:
        def __init__(self, data):
            self.data = iter(data)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read1(self, _):
            return next(self.data, b"")

    opener = Mock()
    monkeypatch.setattr(module, "build_opener", lambda *args: opener)
    opener.open.return_value = Response([b'{"ok":true}'])
    assert module.request_json("https://example.test", {}) == {"ok": True}
    opener.open.return_value = Response([b"x" * 20])
    with pytest.raises(ProviderFailure, match="provider_response_limit"):
        module.request_json("https://example.test", {}, maximum_bytes=10)
    opener.open.return_value = Response([b"not-json"])
    with pytest.raises(ProviderFailure, match="provider_invalid_json"):
        module.request_json("https://example.test", {})
    opener.open.side_effect = HTTPError("https://example.test", 302, "private-error", {}, None)
    with pytest.raises(ProviderFailure) as denied:
        module.request_json("https://example.test", {})
    assert denied.value.code == "provider_http_error" and not denied.value.retryable
    handler = module.NoRedirects()
    assert handler.redirect_request(None, None, 302, "", {}, "https://other.test") is None


def test_ai_timeout_not_retried_and_only_explicit_quota_retry(policy, monkeypatch):
    import practicum_soc.integrations.ai_explanation as module

    retry = policy.model_copy(update={"maximum_retries": 1})
    failure = Mock(side_effect=ProviderFailure("provider_unavailable"))
    monkeypatch.setattr(module, "request_json", failure)
    with pytest.raises(ProviderFailure):
        OpenAIExplanationClient().explain({}, retry)
    assert failure.call_count == 1
    failure.side_effect = ProviderFailure("provider_http_error", retryable=True)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with pytest.raises(ProviderFailure):
        OpenAIExplanationClient().explain({}, retry)
    assert failure.call_count == 3
