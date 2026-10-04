"""Rutas administrativas del catálogo versionado; lógica en servicios reutilizables."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from practicum_soc.core.config import load_json
from practicum_soc.core.paths import PROJECT_ROOT
from practicum_soc.repositories.factory import open_store
from practicum_soc.repositories.rules import RuleConfigStore
from practicum_soc.schemas.rules import Edit, Justification, PreviewRequest
from practicum_soc.services.rule_preview import preview
from practicum_soc.services.rules import RulePageConflict, rules_context

ROOT = PROJECT_ROOT

router = APIRouter()


def admin(request: Request) -> dict:
    actor = request.state.operator
    if not actor or actor.get("role") != "administrator":
        raise HTTPException(403, "Se requiere rol administrador")
    return actor


def versions(store, request) -> RuleConfigStore:
    return RuleConfigStore(store, load_json(request.app.state.config_dir / "detection_rules.json"))


def service_error(error: Exception):
    if isinstance(error, KeyError):
        raise HTTPException(404, "Versión no encontrada") from None
    if isinstance(error, PermissionError):
        raise HTTPException(403, str(error)) from None
    if isinstance(error, FileNotFoundError):
        raise HTTPException(409, "Falta la línea base para la simulación histórica") from None
    raise HTTPException(409 if "cambió" in str(error) else 422, str(error)) from None


@router.get("/admin/rules")
def rules_page(request: Request, draft_id: str | None = None):
    admin(request)
    if draft_id and len(draft_id) > 40:
        raise HTTPException(422, "Identificador de borrador inválido")
    try:
        context = rules_context(
            request.app.state.soc_state_db, request.app.state.config_dir, draft_id
        )
    except KeyError:
        raise HTTPException(404, "Borrador no encontrado") from None
    except RulePageConflict as error:
        raise HTTPException(409, str(error)) from None
    return request.app.state.templates.TemplateResponse(
        request=request, name="rules.html", context=context
    )


@router.get("/api/v1/admin/rule-config")
def current_rules(request: Request):
    admin(request)
    with open_store(request.app.state.soc_state_db) as store:
        service = versions(store, request)
        return {"active": service.current(), "versions": service.versions()}


@router.post("/api/v1/admin/rule-config/drafts")
def create_draft(request: Request):
    actor = admin(request)
    with open_store(request.app.state.soc_state_db) as store:
        try:
            return versions(store, request).create_draft(actor)
        except (ValueError, PermissionError) as error:
            service_error(error)


@router.patch("/api/v1/admin/rule-config/drafts/{draft_id}/rules/{key}")
def change_rule(draft_id: str, key: str, payload: Edit, request: Request):
    actor = admin(request)
    with open_store(request.app.state.soc_state_db) as store:
        try:
            return versions(store, request).update_draft(
                draft_id, actor, payload.expected_hash, key, payload.changes
            )
        except (KeyError, ValueError, PermissionError) as error:
            service_error(error)


@router.patch("/api/v1/admin/rule-config/drafts/{draft_id}/scoring")
def change_scoring(draft_id: str, payload: Edit, request: Request):
    actor = admin(request)
    with open_store(request.app.state.soc_state_db) as store:
        try:
            return versions(store, request).update_draft(
                draft_id, actor, payload.expected_hash, "scoring", payload.changes
            )
        except (KeyError, ValueError, PermissionError) as error:
            service_error(error)


@router.post("/api/v1/admin/rule-config/drafts/{draft_id}/preview")
def simulate(draft_id: str, payload: PreviewRequest, request: Request):
    actor = admin(request)
    with open_store(request.app.state.soc_state_db) as store:
        try:
            return preview(
                store,
                versions(store, request).initial_config,
                load_json(request.app.state.config_dir / "rule_management.json"),
                load_json(request.app.state.config_dir / "operational.json"),
                draft_id,
                actor,
                payload.source,
                payload.from_utc,
                payload.to_utc,
                ROOT,
            )
        except (KeyError, ValueError, PermissionError, FileNotFoundError) as error:
            service_error(error)


@router.post("/api/v1/admin/rule-config/drafts/{draft_id}/publish")
def publish(draft_id: str, payload: Justification, request: Request):
    actor = admin(request)
    with open_store(request.app.state.soc_state_db) as store:
        try:
            return versions(store, request).publish(
                draft_id,
                actor,
                payload.justification,
                load_json(request.app.state.config_dir / "rule_management.json")[
                    "preview_valid_minutes"
                ],
            )
        except (KeyError, ValueError, PermissionError) as error:
            service_error(error)


@router.post("/api/v1/admin/rule-config/versions/{version_id}/restore")
def restore(version_id: str, payload: Justification, request: Request):
    actor = admin(request)
    with open_store(request.app.state.soc_state_db) as store:
        try:
            return versions(store, request).rollback(version_id, actor, payload.justification)
        except (KeyError, ValueError, PermissionError) as error:
            service_error(error)
