"""Protección HTTP y rutas de autenticación; el estado reside en la base SOC."""

import json
import logging
import secrets

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from practicum_soc.api.errors import problem
from practicum_soc.core.auth_config import AuthSettings, origin
from practicum_soc.core.rate_limits import consume, request_scope
from practicum_soc.integrations.oidc import OIDCClient
from practicum_soc.repositories.auth import AuthStore
from practicum_soc.repositories.factory import open_store
from practicum_soc.schemas.auth import UserAccessUpdate
from practicum_soc.services.configuration_audit import observe_configuration

router = APIRouter()


class AuthAccessFilter(logging.Filter):
    def filter(self, record):
        return not any(isinstance(arg, str) and arg.startswith("/auth/") for arg in record.args)


def repository(request):
    return open_store(request.app.state.soc_state_db)


def settings(request):
    return getattr(request.app.state, "auth_settings", None) or AuthSettings.from_env()


def current_session(request, config):
    token = request.cookies.get("soc_session", "")
    if not token:
        return None
    with repository(request) as store:
        background = request.url.path in {
            "/api/dashboard-version",
            "/api/services-version",
            "/api/v1/dashboard/snapshot",
            "/api/v1/dashboard/stream",
        }
        return AuthStore(store, config.policy).session(token, touch=not background)


def consume_request_limit(request, config, scope, subject):
    with repository(request) as store:
        return consume(store, scope, subject, config.policy)


def error_page(request, message: str, status: int):
    return request.app.state.templates.TemplateResponse(
        request=request, name="login.html", context={"message": message}, status_code=status
    )


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def authenticate(self, request):
        request.state.operator = None
        request.state.csrf_token = ""
        path = request.url.path
        public = path in {"/auth/login", "/auth/callback", "/auth/logged-out", "/healthz"}
        public = public or path.startswith("/static/")
        try:
            config = settings(request)
            if config.mode == "disabled":
                if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
                    return JSONResponse(
                        {"detail": "Modo local limitado a loopback"}, status_code=403
                    )
                request.state.operator = {
                    "user_id": "local",
                    "display_name": "Operador local",
                    "role": "administrator",
                    "enabled": 1,
                }
            elif not public:
                user = await run_in_threadpool(current_session, request, config)
                if not user:
                    if (
                        request.method == "GET"
                        and "text/html" in request.headers.get("accept", "")
                        and not path.startswith("/api/")
                    ):
                        return RedirectResponse("/auth/login", status_code=303)
                    return JSONResponse({"detail": "Debe iniciar sesión"}, status_code=401)
                request.state.operator = user
                request.state.csrf_token = user["csrf_token"]
                if path.startswith("/admin") and user["role"] != "administrator":
                    logging.getLogger(__name__).warning("security_event=administrator_role_denied")
                    return JSONResponse(
                        {"detail": "Se requiere rol administrador"}, status_code=403
                    )
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    supplied = request.headers.get("x-csrf-token", "")
                    if not secrets.compare_digest(supplied, user["csrf_token"]):
                        logging.getLogger(__name__).warning("security_event=csrf_rejected")
                        return JSONResponse({"detail": "Token CSRF inválido"}, status_code=403)
                    if request.headers.get("origin", origin(config.public_url)) != origin(
                        config.public_url
                    ):
                        logging.getLogger(__name__).warning("security_event=origin_rejected")
                        return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
            scope = request_scope(request.method, path)
            if config.mode == "oidc" and scope:
                operator = request.state.operator
                subject = (
                    "user:" + operator["user_id"]
                    if operator
                    else "peer:" + (request.client.host if request.client else "unknown")
                )
                retry = await run_in_threadpool(
                    consume_request_limit, request, config, scope, subject
                )
                if retry:
                    logging.getLogger(__name__).warning(
                        "security_event=rate_limited scope=%s", scope
                    )
                    return JSONResponse(
                        {"detail": "Demasiadas solicitudes. Inténtalo más tarde."},
                        status_code=429,
                        headers={"Retry-After": str(retry)},
                    )
        except Exception as error:
            logging.getLogger(__name__).error(
                "security_event=authentication_unavailable type=%s", type(error).__name__
            )
            return JSONResponse(
                {"detail": "Autenticación temporalmente no disponible"}, status_code=503
            )
        return None

    async def dispatch(self, request, call_next):
        response = await self.authenticate(request)
        if response is not None and request.url.path.startswith("/api/v1/"):
            response = problem(
                response.status_code,
                json.loads(response.body)["detail"],
                headers={"Retry-After": response.headers["Retry-After"]}
                if "Retry-After" in response.headers
                else None,
            )
        if response is None:
            response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
        return response


@router.get("/auth/login")
def login(request: Request):
    config = settings(request)
    if config.mode == "disabled":
        return RedirectResponse("/", status_code=303)
    if origin(str(request.url)) != origin(config.public_url):
        return RedirectResponse(config.public_url + "/auth/login", status_code=303)
    try:
        client = OIDCClient(config)
        with repository(request) as store:
            state, browser, nonce, verifier = AuthStore(store, config.policy).begin_login()
        response = RedirectResponse(client.authorize_url(state, nonce, verifier), status_code=303)
        response.set_cookie(
            "soc_login",
            browser,
            max_age=config.policy["login_attempt_seconds"],
            httponly=True,
            secure=config.secure_cookie,
            samesite="lax",
            path="/auth",
        )
        return response
    except Exception:
        return error_page(
            request, "El proveedor de acceso aún no está disponible. Inténtalo de nuevo.", 503
        )


@router.get("/auth/callback")
def callback(
    request: Request,
    state: str = Query("", max_length=512),
    code: str = Query("", max_length=2048),
):
    config = settings(request)
    try:
        if not state or not code:
            raise ValueError("Falta respuesta OIDC")
        with repository(request) as store:
            auth = AuthStore(store, config.policy)
            attempt = auth.consume_login(state, request.cookies.get("soc_login", ""))
            claims = OIDCClient(config).exchange(code, attempt["nonce"], attempt["verifier"])
            old_token = request.cookies.get("soc_session", "")
            old_user = auth.session(old_token) if old_token else None
            if old_user:
                auth.logout(old_token, old_user)
            session_token = auth.login(claims)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            "soc_session",
            session_token,
            max_age=config.policy["session_absolute_seconds"],
            httponly=True,
            secure=config.secure_cookie,
            samesite="lax",
            path="/",
        )
    except Exception:
        logging.getLogger(__name__).warning("security_event=oidc_callback_rejected")
        response = error_page(
            request,
            "No se pudo autorizar el acceso. Reinicia el inicio de sesión o consulta al administrador.",
            403,
        )
    response.delete_cookie("soc_login", path="/auth")
    return response


@router.post("/auth/logout")
def logout(request: Request):
    config = settings(request)
    with repository(request) as store:
        AuthStore(store, config.policy).logout(
            request.cookies.get("soc_session", ""), request.state.operator
        )
    try:
        url = OIDCClient(config).logout_url()
    except Exception:
        url = config.public_url + "/auth/logged-out"
    response = JSONResponse({"redirect": url})
    response.delete_cookie("soc_session", path="/")
    return response


@router.get("/auth/logged-out")
def logged_out(request: Request):
    return error_page(request, "Tu sesión en la plataforma se ha cerrado.", 200)


@router.get("/auth/me")
def me(request: Request):
    user = request.state.operator
    return {
        "user_id": user["user_id"],
        "display_name": user["display_name"],
        "role": user["role"],
        "csrf_token": request.state.csrf_token,
    }


@router.get("/admin/users")
def users(request: Request):
    with repository(request) as store:
        auth = AuthStore(store, settings(request).policy)
        context = {"users": auth.users(), "audit": auth.audit_entries()}
    return request.app.state.templates.TemplateResponse(
        request=request, name="users.html", context=context
    )


@router.get("/admin/configuration")
def configuration(request: Request):
    with repository(request) as store:
        policy = settings(request).policy
        snapshots = observe_configuration(store, request.app.state.config_dir, policy)
        audit = AuthStore(store, policy).audit_entries(
            ("configuration_baseline", "configuration_change_detected")
        )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="configuration.html",
        context={"snapshots": snapshots, "audit": audit},
    )


@router.patch("/admin/users/{user_id}")
def update_user(user_id: str, payload: UserAccessUpdate, request: Request):
    try:
        with repository(request) as store:
            AuthStore(store, settings(request).policy).update_user(
                user_id, payload.role, payload.enabled, request.state.operator
            )
        return {"updated": True}
    except KeyError:
        raise HTTPException(404, "Usuario no encontrado") from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    except PermissionError:
        raise HTTPException(403, "Se requiere rol administrador") from None
