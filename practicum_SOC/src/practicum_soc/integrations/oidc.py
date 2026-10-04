"""Authorization Code con PKCE y validación criptográfica del ID token."""

import base64
import hashlib
import json
import secrets
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


class OIDCClient:
    def __init__(self, settings):
        settings.validate()
        self.settings = settings

    def request_json(self, url: str, data: dict | None = None):
        request = Request(
            self.settings.transport_url(url),
            data=urlencode(data).encode() if data is not None else None,
            headers={"Accept": "application/json"},
        )
        with build_opener(NoRedirects).open(
            request, timeout=self.settings.policy["http_timeout_seconds"]
        ) as response:
            body = response.read(self.settings.policy["maximum_http_bytes"] + 1)
        if len(body) > self.settings.policy["maximum_http_bytes"]:
            raise ValueError("Respuesta OIDC demasiado grande")
        return json.loads(body)

    def metadata(self):
        metadata = self.request_json(self.settings.issuer + "/.well-known/openid-configuration")
        if metadata["issuer"] != self.settings.issuer:
            raise ValueError("Issuer de discovery inesperado")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            self.settings.transport_url(metadata[key])
        return metadata

    def authorize_url(self, state: str, nonce: str, verifier: str):
        return (
            self.metadata()["authorization_endpoint"]
            + "?"
            + urlencode(
                {
                    "client_id": self.settings.client_id,
                    "response_type": "code",
                    "redirect_uri": self.settings.public_url + "/auth/callback",
                    "scope": "openid profile",
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": challenge(verifier),
                    "code_challenge_method": "S256",
                }
            )
        )

    def exchange(self, code: str, nonce: str, verifier: str):
        metadata = self.metadata()
        tokens = self.request_json(
            metadata["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.public_url + "/auth/callback",
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "code_verifier": verifier,
            },
        )
        token = tokens["id_token"]
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise ValueError("Algoritmo no permitido")
        keys = self.request_json(metadata["jwks_uri"])["keys"]
        jwk = next(
            key
            for key in keys
            if key.get("kid") == header.get("kid")
            and key.get("kty") == "RSA"
            and key.get("use", "sig") == "sig"
        )
        claims = jwt.decode(
            token,
            jwt.PyJWK.from_dict(jwk).key,
            algorithms=["RS256"],
            audience=self.settings.client_id,
            issuer=self.settings.issuer,
            leeway=self.settings.policy["clock_leeway_seconds"],
            options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce"]},
        )
        if not secrets.compare_digest(str(claims["nonce"]), nonce):
            raise ValueError("Nonce inválido")
        if claims.get("azp", self.settings.client_id) != self.settings.client_id:
            raise ValueError("Cliente autorizado inesperado")
        if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and not claims.get("azp"):
            raise ValueError("Token multiaudiencia sin cliente autorizado")
        return claims

    def logout_url(self):
        endpoint = self.metadata().get("end_session_endpoint")
        if not endpoint:
            return self.settings.public_url + "/auth/logged-out"
        self.settings.transport_url(endpoint)
        return (
            endpoint
            + "?"
            + urlencode(
                {
                    "client_id": self.settings.client_id,
                    "post_logout_redirect_uri": self.settings.public_url + "/auth/logged-out",
                }
            )
        )
