"""Publicación de reglas, comparación histórica y control de acceso."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_alert_store import sample_alert
from test_postgres_store import pg_store  # noqa: F401

import practicum_soc.main as web_app
from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.integrations.notifications import SocInboxProvider
from practicum_soc.repositories.alerts import AlertStore
from practicum_soc.repositories.auth import AuthStore
from practicum_soc.repositories.rules import RuleConfigStore, edited_rule, edited_scoring
from practicum_soc.services.monitoring import run_monitor_cycle
from practicum_soc.services.rule_preview import preview
from practicum_soc.soc.normalization import NormalizationConfig

ROOT = Path(__file__).resolve().parents[1]
INITIAL = json.loads((ROOT / "config/detection_rules.json").read_text(encoding="utf-8"))
MANAGEMENT = json.loads((ROOT / "config/rule_management.json").read_text(encoding="utf-8"))


def admin() -> dict:
    return {"user_id": "local", "display_name": "Operador de prueba", "role": "administrator"}


def baseline(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "baseline_summary.json").write_text(
        json.dumps({"training_period": {"end_local": "2026-03-20"}}), encoding="utf-8"
    )
    for name in (
        "user_behavior.csv",
        "user_ip_profile.csv",
        "user_app_profile.csv",
        "user_hour_profile.csv",
    ):
        (directory / name).write_text("user_key,history_status\n", encoding="utf-8")


def events(store) -> None:
    for index in range(6):
        timestamp = f"2026-03-21T15:0{index}:00+00:00"
        event = {
            "source_event_id": f"synthetic-{index}",
            "event_time_utc": timestamp,
            "event_class": "failure",
            "event_count": 1,
            "user_key": "usr_synthetic",
            "client_ip_key": "ip_synthetic",
            "relying_party": "app_synthetic",
        }
        assert store.insert_event(event, timestamp, str(index), True, "csv_demo_mvp")


def test_controlled_ranges_and_no_new_rule_names():
    with pytest.raises(ValueError):
        edited_rule(INITIAL, "after_hours", {"enabled": True})
    with pytest.raises(ValueError):
        edited_rule(INITIAL, "brute_force_user", {"minimum_failures": 0})
    with pytest.raises(ValueError):
        edited_rule(INITIAL, "brute_force_user", {"base_risk": "85"})
    with pytest.raises(ValueError):
        edited_scoring(
            INITIAL,
            {
                "severity_thresholds": {
                    "low": 0,
                    "medium": 60,
                    "high": 50,
                    "critical": 85,
                }
            },
        )


def test_draft_preview_publish_restore_and_case_version(tmp_path):
    database = tmp_path / "soc.db"
    baseline(tmp_path / "baseline")
    (tmp_path / "exclusions.json").write_text("{}", encoding="utf-8")
    operational = {"baseline_dir": "baseline", "exclusions_file": "exclusions.json"}
    with AlertStore(database) as store:
        manager = RuleConfigStore(store, INITIAL)
        original = manager.current()
        draft = manager.create_draft(admin())
        assert manager.current()["version_id"] == original["version_id"]
        with pytest.raises(ValueError, match="Modifique"):
            manager.publish(draft["version_id"], admin(), "Subir umbral tras revisión", 60)
        changed = manager.update_draft(
            draft["version_id"],
            admin(),
            draft["payload_hash"],
            "brute_force_user",
            {"minimum_failures": 7},
        )
        with pytest.raises(ValueError, match="cambió"):
            manager.update_draft(
                draft["version_id"],
                admin(),
                draft["payload_hash"],
                "brute_force_user",
                {"minimum_failures": 8},
            )
        events(store)
        before = store.connection.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"]
        result = preview(
            store,
            INITIAL,
            MANAGEMENT,
            operational,
            draft["version_id"],
            admin(),
            "csv_demo_mvp",
            datetime(2026, 3, 21, 15, tzinfo=UTC),
            datetime(2026, 3, 21, 16, tzinfo=UTC),
            tmp_path,
        )
        assert result["active"]["by_rule"]["AUTH_BRUTE_FORCE_USER"] == 1
        assert result["draft"]["total"] == 0
        assert result["difference"] == -1
        assert (
            store.connection.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"] == before
        )
        with pytest.raises(ValueError, match="Pruebe"):
            manager.update_draft(
                changed["version_id"],
                admin(),
                changed["payload_hash"],
                "brute_force_user",
                {"minimum_failures": 8},
            )
            manager.publish(draft["version_id"], admin(), "Nuevo umbral justificado", 60)
        result = preview(
            store,
            INITIAL,
            MANAGEMENT,
            operational,
            draft["version_id"],
            admin(),
            "csv_demo_mvp",
            datetime(2026, 3, 21, 15, tzinfo=UTC),
            datetime(2026, 3, 21, 16, tzinfo=UTC),
            tmp_path,
        )
        published = manager.publish(draft["version_id"], admin(), "Reducir señales repetidas", 60)
        assert published["version_id"] == draft["version_id"]
        alert = sample_alert("versioned-case")
        alert["rule_version_id"] = published["version_id"]
        assert store.insert_alert(alert)[0]
        assert store.get_alert("versioned-case")["rule_version_id"] == published["version_id"]
        restored = manager.rollback(original["version_id"], admin(), "Reponer parámetros previos")
        assert restored["version_id"] == original["version_id"]
        assert store.get_alert("versioned-case")["rule_version_id"] == published["version_id"]
        assert [row["action"] for row in manager.history()].count("published") == 1
    with AlertStore(database) as reopened:
        assert RuleConfigStore(reopened, INITIAL).current()["version_id"] == original["version_id"]


def test_pg_versions_and_restore(pg_store):  # noqa: F811
    store, _, _ = pg_store
    manager = RuleConfigStore(store, INITIAL)
    active = manager.current()
    draft = manager.create_draft(admin())
    events(store)
    assert len(manager.versions()) == 2
    assert manager.current()["version_id"] == active["version_id"]
    assert (
        store.connection.execute("SELECT COUNT(*) AS n FROM rule_config_versions").fetchone()["n"]
        == 2
    )
    assert draft["status"] == "draft"


def test_monitor_cycle_reads_only_the_published_version(tmp_path):
    class EmptySource:
        source_name = "csv_demo"

        def fetch_after(self, checkpoint, limit):
            return []

    operational = {
        "batch_size": 20,
        "notification_policy": {
            "immediate_severities": ["high", "critical"],
            "maximum_notifications_per_run": 10,
            "maximum_delivery_attempts": 2,
        },
    }
    with AlertStore(tmp_path / "monitor.db") as store:
        manager = RuleConfigStore(store, INITIAL)
        initial = manager.current()
        draft = manager.create_draft(admin())
        changed = manager.update_draft(
            draft["version_id"],
            admin(),
            draft["payload_hash"],
            "brute_force_user",
            {"minimum_failures": 7},
        )

        def cycle():
            return run_monitor_cycle(
                source=EmptySource(),
                store=store,
                secret=b"synthetic-secret",
                normalization_config=NormalizationConfig.from_file(
                    ROOT / "config/normalization.json"
                ),
                detection_config=INITIAL,
                operational_config=operational,
                provider=SocInboxProvider(),
            )

        assert cycle()["rule_version_id"] == initial["version_id"]
        manager.save_preview(
            draft["version_id"],
            admin(),
            initial["version_id"],
            "csv_demo",
            "2026-03-21T00:00:00+00:00",
            "2026-03-22T00:00:00+00:00",
            {"active": {"total": 1}, "draft": {"total": 0}},
        )
        assert manager.version(draft["version_id"])["payload_hash"] == changed["payload_hash"]
        published = manager.publish(
            draft["version_id"], admin(), "Validación sintética de prueba", 60
        )
        assert cycle()["rule_version_id"] == published["version_id"]


def test_stale_draft_and_preview_limit_are_explicit(tmp_path):
    baseline(tmp_path / "baseline")
    (tmp_path / "exclusions.json").write_text("{}", encoding="utf-8")
    with AlertStore(tmp_path / "limits.db") as store:
        manager = RuleConfigStore(store, INITIAL)
        active = manager.current()
        first = manager.create_draft(admin())
        stale = manager.create_draft(admin())
        manager.update_draft(
            first["version_id"],
            admin(),
            first["payload_hash"],
            "brute_force_user",
            {"minimum_failures": 7},
        )
        events(store)
        with pytest.raises(ValueError, match="Demasiados eventos"):
            preview(
                store,
                INITIAL,
                {**MANAGEMENT, "maximum_preview_events": 5},
                {"baseline_dir": "baseline", "exclusions_file": "exclusions.json"},
                first["version_id"],
                admin(),
                "csv_demo_mvp",
                datetime(2026, 3, 21, 15, tzinfo=UTC),
                datetime(2026, 3, 21, 16, tzinfo=UTC),
                tmp_path,
            )
        assert (
            store.connection.execute("SELECT COUNT(*) AS n FROM rule_config_previews").fetchone()[
                "n"
            ]
            == 0
        )
        manager.save_preview(
            first["version_id"],
            admin(),
            active["version_id"],
            "csv_demo_mvp",
            "2026-03-21T15:00:00+00:00",
            "2026-03-21T16:00:00+00:00",
            {"active": {"total": 1}, "draft": {"total": 1}},
        )
        manager.publish(first["version_id"], admin(), "Publicación de la primera versión", 60)
        with pytest.raises(ValueError, match="ya no parte"):
            manager.publish(stale["version_id"], admin(), "Otra publicación tardía", 60)


def test_admin_api_protects_drafts_and_csrf(monkeypatch, tmp_path):
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SOC_AUTH_MODE", "oidc")
    monkeypatch.setenv("SOC_PUBLIC_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("SOC_OIDC_ISSUER", "http://127.0.0.1:8080/realms/soc")
    monkeypatch.setenv("SOC_OIDC_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr(web_app.app.state, "soc_state_db", tmp_path / "api.db")
    monkeypatch.setattr(web_app.app.state, "config_dir", ROOT / "config")
    client = TestClient(web_app.app, base_url="http://127.0.0.1:8000")
    endpoint = "/api/v1/admin/rule-config/drafts"
    assert client.post(endpoint).status_code == 401
    settings = AuthSettings.from_env()
    with AlertStore(tmp_path / "api.db") as store:
        auth = AuthStore(store, settings.policy)
        analyst_token = auth.login({"iss": "test", "sub": "analyst", "soc_roles": ["analyst"]})
        admin_token = auth.login({"iss": "test", "sub": "admin", "soc_roles": ["administrator"]})
        admin_session = auth.session(admin_token)
    client.cookies.set("soc_session", analyst_token)
    assert client.get("/admin/rules").status_code == 403
    assert client.post(endpoint, headers={"X-CSRF-Token": "invalid"}).status_code == 403
    client.cookies.set("soc_session", admin_token)
    assert client.get("/admin/rules").status_code == 200
    assert client.post(endpoint).status_code == 403
    headers = {"X-CSRF-Token": admin_session["csrf_token"]}
    response = client.post(endpoint, headers=headers)
    assert response.status_code == 200
    draft = response.json()
    assert (
        client.patch(
            f"{endpoint}/{draft['version_id']}/rules/brute_force_user",
            headers=headers,
            json={"expected_hash": draft["payload_hash"], "changes": {"minimum_failures": -1}},
        ).status_code
        == 422
    )
    with AlertStore(tmp_path / "api.db") as store:
        assert RuleConfigStore(store, INITIAL).current()["version_id"] == draft["parent_version_id"]


def test_rule_editor_renders_catalog_fields_and_publication_guards(monkeypatch, tmp_path):
    """El rediseño conserva campos, rangos y la separación entre borrador y monitor."""
    monkeypatch.setenv("SOC_ENV", "local")
    monkeypatch.setenv("SOC_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SOC_AUTH_MODE", "disabled")
    monkeypatch.setenv("SOC_PUBLIC_URL", "http://127.0.0.1:8000")
    database = tmp_path / "editor.db"
    monkeypatch.setattr(web_app.app.state, "soc_state_db", database)
    client = TestClient(web_app.app, base_url="http://127.0.0.1:8000")
    response = client.get("/admin/rules")
    assert response.status_code == 200
    assert "Prepara un ajuste controlado" in response.text
    assert "data-rule-form=" not in response.text
    with AlertStore(database) as store:
        manager = RuleConfigStore(store, INITIAL)
        active = manager.current()
        draft = manager.create_draft(admin())
    response = client.get(f"/admin/rules?draft_id={draft['version_id']}")
    assert response.status_code == 200
    html = response.text
    assert html.count('data-rule-form="') == 5
    assert html.count('data-rule-select="') == 6
    assert html.count('data-rule-panel="') == 6
    assert html.count('<fieldset class="rules-parameter-group">') == 15
    assert "Condición de detección" in html
    assert "Control de repetición" in html
    assert "Puntaje y escalamiento" in html
    assert "Aún no hay una comparación" in html
    assert "disabled>Publicar versión</button>" in html
    assert "disabled>Simular y comparar</button>" in html
    assert 'name="minimum_failures" data-active-value="6"' in html
    assert 'data-score-range="high">65–84' in html
    with AlertStore(database) as store:
        assert RuleConfigStore(store, INITIAL).current() == active
