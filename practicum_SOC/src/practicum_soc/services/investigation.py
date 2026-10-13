"""Coordina permisos, contexto, fuentes y validación sin modificar el detector."""

import copy
import json
from decimal import Decimal
from pathlib import Path

from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.core.investigation_config import InvestigationSettings, InvestigationUnavailable
from practicum_soc.core.paths import PROJECT_ROOT
from practicum_soc.core.private_ip import decrypt_payload, is_public_ip
from practicum_soc.integrations.ai_explanation import OpenAIExplanationClient
from practicum_soc.integrations.investigation_http import ProviderFailure
from practicum_soc.integrations.ip_reputation import IPReputationClient
from practicum_soc.repositories.auth import AuthStore
from practicum_soc.repositories.factory import open_store
from practicum_soc.repositories.investigation import InvestigationRepository
from practicum_soc.schemas.investigation import (
    AIExplanation,
    InvestigationJob,
    InvestigationResult,
    ReputationResult,
)
from practicum_soc.services.investigation_context import collect_context


def require_operator(actor):
    if (
        not actor
        or not actor.get("enabled", False)
        or actor.get("role") not in {"analyst", "administrator"}
    ):
        raise PermissionError("Se requiere un analista o administrador autorizado")


def audit(store, actor, action, target, details=None):
    with store.connection:
        AuthStore(store, AuthSettings.from_env().policy).audit(actor, action, target, details)


def present_job(job, *, reused=False):
    result = (
        InvestigationResult.model_validate(decrypt_payload(job["result_ciphertext"]))
        if job.get("result_ciphertext")
        else None
    )
    public = {
        key: job.get(key)
        for key in (
            "analysis_id",
            "alert_id",
            "status",
            "requested_by",
            "created_at_utc",
            "started_at_utc",
            "finished_at_utc",
            "error_code",
        )
    }
    return InvestigationJob(
        **public,
        result=result,
        reused=reused,
        real_ip=result.real_ip if result else None,
        real_ip_unavailable_reason=result.real_ip_unavailable_reason
        if result
        else "La investigación aún no tiene un resultado disponible",
    )


def request_investigation(store, alert_id, actor, policy, *, force_new=False):
    require_operator(actor)
    if store.get_alert(alert_id) is None:
        raise KeyError(alert_id)
    policy.require_available()
    job, reused = InvestigationRepository(store).enqueue(
        alert_id, actor["user_id"], policy, force_new=force_new
    )
    audit(
        store,
        actor,
        "investigation_requested",
        job["analysis_id"],
        {"alert_id": alert_id, "reused": reused, "force_new": force_new},
    )
    return present_job(job, reused=reused)


def retrieve_investigation(store, alert_id, analysis_id, actor):
    require_operator(actor)
    job = InvestigationRepository(store).get(analysis_id)
    if not job or job["alert_id"] != alert_id:
        raise KeyError(analysis_id)
    result = present_job(job)
    audit(store, actor, "investigation_viewed", analysis_id, {"alert_id": alert_id})
    return result


def limited_context(context, reputation, addresses, policy):
    model_context = copy.deepcopy(context)
    model_context["reputation"] = [
        item.model_dump(exclude=set() if policy.send_real_ip_to_ai else {"ip_address"})
        for item in reputation
    ]
    if policy.send_real_ip_to_ai:
        model_context["real_ips"] = addresses
    # Los textos originales ya están excluidos; limitar también la representación total.
    while (
        len(json.dumps(model_context, ensure_ascii=False).encode("utf-8"))
        > policy.maximum_context_bytes
    ):
        if not model_context["events"]:
            raise ProviderFailure("context_limit")
        model_context["events"].pop()
    kept = {row["source_event_id"] for row in model_context["events"]}
    model_context["success_after_failure_event_ids"] = [
        key for key in model_context["success_after_failure_event_ids"] if key in kept
    ]
    if len(model_context["events"]) != len(context["events"]):
        model_context["sampling_note"] = (
            "Detalle recortado por límite de contexto; conteos calculados por backend."
        )
    # Comprobar una vez más después de cambiar la nota.
    if (
        len(json.dumps(model_context, ensure_ascii=False).encode("utf-8"))
        > policy.maximum_context_bytes
    ):
        raise ProviderFailure("context_limit")
    return model_context


def validated_explanation(value, model_context):
    explanation = AIExplanation.model_validate(value)
    allowed = {row["source_event_id"] for row in model_context["events"]}
    allowed.update({"alert", "baseline", "reputation"})
    if any(ref not in allowed for evidence in explanation.evidence for ref in evidence.references):
        raise ProviderFailure("ai_unknown_evidence")
    return explanation


def token_cost(tokens, policy):
    usage = {
        name: int(tokens[name]) if tokens.get(name) is not None else None
        for name in ("input_tokens", "output_tokens")
    }
    if any(value is not None and (value < 0 or value > 1000000) for value in usage.values()):
        raise ProviderFailure("ai_invalid_usage")
    usage.update({"provider": policy.provider, "model": policy.model, "estimated_cost_usd": None})
    if (
        policy.input_usd_per_million_tokens is not None
        and policy.output_usd_per_million_tokens is not None
        and usage["input_tokens"] is not None
        and usage["output_tokens"] is not None
    ):
        cost = (
            Decimal(usage["input_tokens"]) * Decimal(str(policy.input_usd_per_million_tokens))
            + Decimal(usage["output_tokens"]) * Decimal(str(policy.output_usd_per_million_tokens))
        ) / 1000000
        usage["estimated_cost_usd"] = str(cost.quantize(Decimal("0.00000001")))
    return usage


class InvestigationWorker:
    def __init__(
        self, state_db: Path, *, ai=None, reputation=None, baseline_dir=None, store_factory=None
    ):
        self.state_db = state_db
        self.ai = ai or OpenAIExplanationClient()
        self.reputation = reputation or IPReputationClient()
        self.baseline_dir = baseline_dir or PROJECT_ROOT / "analysis/baseline"
        self.store_factory = store_factory or open_store

    def _claim_and_collect(self, policy):
        with self.store_factory(self.state_db) as store:
            repository = InvestigationRepository(store)
            job = repository.claim(policy)
        if job is None:
            return None
        # Guardar el estado antes de leer contexto; cualquier fallo posterior deja un job recuperable.
        return job

    def run_once(self, policy):
        job = self._claim_and_collect(policy)
        if job is None:
            return None
        result, error_code = None, None
        try:
            saved_policy = InvestigationSettings.model_validate_json(job["policy_json"])
            saved_policy.require_available()
            with self.store_factory(self.state_db) as store:
                user = store.connection.execute(
                    "SELECT role,enabled FROM platform_users WHERE user_id=?",
                    (job["requested_by"],),
                ).fetchone()
                local = (
                    job["requested_by"] == "local" and AuthSettings.from_env().mode == "disabled"
                )
                if not local:
                    require_operator(dict(user) if user else None)
                alert = store.get_alert(job["alert_id"])
                if not alert:
                    raise ProviderFailure("alert_not_found")
                context, real_ip, addresses, reason = collect_context(
                    store, alert, saved_policy, self.baseline_dir
                )
            reputation = self._reputations(addresses, saved_policy)
            model_context = limited_context(context, reputation, addresses, saved_policy)
            value, tokens = self.ai.explain(model_context, saved_policy)
            explanation = validated_explanation(value, model_context)
            result = InvestigationResult(
                alert_id=job["alert_id"],
                analysis_id=job["analysis_id"],
                real_ip=real_ip,
                real_ips=addresses,
                real_ip_unavailable_reason=reason,
                context=context,
                reputation=reputation,
                explanation=explanation,
                usage=token_cost(tokens, saved_policy),
            ).model_dump(mode="json")
        except ProviderFailure as error:
            error_code = error.code
        except PermissionError:
            error_code = "requester_access_revoked"
        except InvestigationUnavailable:
            error_code = "investigation_configuration_unavailable"
        except Exception:
            # Nunca almacenar excepciones del proveedor, IP, prompts o credenciales en errores/logs.
            error_code = "investigation_failed"
        with self.store_factory(self.state_db) as store:
            InvestigationRepository(store).finish(job, result, error_code)
        return job["analysis_id"]

    def _reputations(self, addresses, policy):
        results = []
        for address in addresses:
            # La comprobación vive también en la coordinación, aun con un cliente sustituido.
            if not is_public_ip(address):
                results.append(
                    ReputationResult(
                        status="not_applicable", reason="IP no pública; análisis interno"
                    )
                )
                continue
            try:
                results.append(
                    ReputationResult.model_validate(self.reputation.check(address, policy))
                )
            except Exception:
                results.append(
                    ReputationResult(status="unavailable", reason="Reputación no disponible")
                )
        return [
            item.model_copy(update={"ip_address": address})
            for address, item in zip(addresses, results, strict=True)
        ]
