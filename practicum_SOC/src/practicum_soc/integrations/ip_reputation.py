"""AbuseIPDB opcional: solo lectura de IP globales; ninguna IP se reporta."""

import ipaddress
import os
from urllib.parse import urlencode

from practicum_soc.core.private_ip import is_public_ip
from practicum_soc.integrations.investigation_http import request_json
from practicum_soc.repositories.alerts import utc_now
from practicum_soc.schemas.investigation import ReputationResult


class IPReputationClient:
    def check(self, address: str, policy) -> ReputationResult:
        parsed = ipaddress.ip_address(address)
        if not is_public_ip(address):
            return ReputationResult(
                status="not_applicable", reason="IP no pública; análisis interno"
            )
        if os.environ.get("SOC_IP_REPUTATION_ENABLED", "false").casefold() != "true":
            return ReputationResult(status="disabled", reason="Reputación externa deshabilitada")
        checked = utc_now()
        if not os.environ.get("ABUSEIPDB_API_KEY", ""):
            return ReputationResult(
                status="unavailable",
                provider="abuseipdb",
                checked_at_utc=checked,
                reason="Falta ABUSEIPDB_API_KEY",
            )
        try:
            response = request_json(
                "https://api.abuseipdb.com/api/v2/check?" + urlencode({"ipAddress": address}),
                {"Key": os.environ["ABUSEIPDB_API_KEY"]},
                timeout=policy.reputation_timeout_seconds,
                maximum_bytes=policy.maximum_response_bytes,
            )["data"]
            if ipaddress.ip_address(response["ipAddress"]) != parsed:
                raise ValueError("La fuente respondió por otra IP")
            return ReputationResult(
                status="available",
                provider="abuseipdb",
                checked_at_utc=checked,
                abuse_confidence_score=response["abuseConfidenceScore"],
                total_reports=response["totalReports"],
            )
        except (ValueError, KeyError, TypeError):
            return ReputationResult(
                status="unavailable",
                provider="abuseipdb",
                checked_at_utc=checked,
                reason="Fuente externa no disponible o respuesta inválida",
            )
