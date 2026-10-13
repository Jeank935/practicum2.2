"""API de investigación: sesión, CSRF y límites existentes protegen estas rutas."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, Response

from practicum_soc.core.investigation_config import InvestigationSettings, InvestigationUnavailable
from practicum_soc.repositories.factory import open_store
from practicum_soc.repositories.investigation import InvestigationQueueFull
from practicum_soc.schemas.investigation import InvestigationJob, InvestigationRequest
from practicum_soc.services.investigation import request_investigation, retrieve_investigation

router = APIRouter(prefix="/api/v1/alerts", tags=["Investigación asistida"])
Identifier = Annotated[str, Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]


@router.post("/{alert_id}/investigations", response_model=InvestigationJob, status_code=202)
def investigate(
    alert_id: Identifier, payload: InvestigationRequest, request: Request, response: Response
):
    try:
        policy = InvestigationSettings.load(request.app.state.config_dir / "investigation.json")
        with open_store(request.app.state.soc_state_db) as store:
            result = request_investigation(
                store, alert_id, request.state.operator, policy, force_new=payload.force_new
            )
    except PermissionError as error:
        raise HTTPException(403, str(error)) from None
    except KeyError:
        raise HTTPException(404, "Alerta no encontrada") from None
    except InvestigationQueueFull as error:
        raise HTTPException(429, str(error), headers={"Retry-After": "30"}) from None
    except InvestigationUnavailable as error:
        raise HTTPException(503, str(error)) from None
    response.status_code = 200 if result.status == "completed" else 202
    response.headers["Location"] = f"/api/v1/alerts/{alert_id}/investigations/{result.analysis_id}"
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/{alert_id}/investigations/{analysis_id}", response_model=InvestigationJob)
def result(alert_id: Identifier, analysis_id: Identifier, request: Request, response: Response):
    try:
        with open_store(request.app.state.soc_state_db) as store:
            job = retrieve_investigation(store, alert_id, analysis_id, request.state.operator)
    except PermissionError as error:
        raise HTTPException(403, str(error)) from None
    except KeyError:
        raise HTTPException(404, "Análisis no encontrado") from None
    except InvestigationUnavailable as error:
        raise HTTPException(503, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return job
