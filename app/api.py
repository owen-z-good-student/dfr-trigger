from typing import Optional,  Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.config_store import ConfigStore
from app.schemas import (
    ConfigStatus,
    ConfigWrite,
    DispatchRequest,
    DispatchResult,
    GeocodeRequest,
    GeocodeResponse,
)
from app.security import require_state_change, trusted_actor


router = APIRouter(prefix="/api")


def _config_store(request: Request) -> ConfigStore:
    store = request.app.state.config_store
    if store is None:
        raise HTTPException(503, "configuration store is unavailable")
    return store


@router.get("/config", response_model=ConfigStatus)
def get_config(request: Request) -> ConfigStatus:
    trusted_actor(request)
    try:
        return _config_store(request).status()
    except ValueError as error:
        raise HTTPException(503, "configuration store is unavailable") from error


@router.put("/config", response_model=ConfigStatus)
def put_config(request: Request, value: ConfigWrite) -> ConfigStatus:
    require_state_change(request)
    actor = trusted_actor(request)
    return _config_store(request).save(value, actor)


@router.post("/config/test")
def test_config(request: Request) -> dict[str, bool]:
    require_state_change(request)
    trusted_actor(request)
    try:
        config = _config_store(request).load()
    except ValueError as error:
        raise HTTPException(503, "configuration store is unavailable") from error
    if config is None:
        raise HTTPException(503, "FH2 configuration is incomplete")
    return {"valid": True, "fh2_request_sent": False}


@router.post("/dispatch", response_model=DispatchResult)
async def dispatch(
    request: Request,
    value: DispatchRequest,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            pattern=r"^[A-Za-z0-9_-]{16,128}$",
        ),
    ],
) -> DispatchResult:
    require_state_change(request)
    actor = trusted_actor(request)
    return await request.app.state.dispatch_service.submit(
        value, actor, idempotency_key
    )


@router.get("/logs")
def logs(
    request: Request,
    query: Optional[str] = None,
    priority: Optional[int] = Query(default=None, ge=1, le=5),
    outcome: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = None,
) -> dict:
    trusted_actor(request)
    try:
        return request.app.state.audit_store.list(
            query=query,
            priority=priority,
            outcome=outcome,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode(request: Request, value: GeocodeRequest) -> GeocodeResponse:
    require_state_change(request)
    actor = trusted_actor(request)
    settings = request.app.state.settings
    try:
        request.app.state.limiter.check(
            "geocode-user", actor, settings.geocodes_per_user_per_minute, 60
        )
        request.app.state.limiter.check(
            "geocode-instance", "instance",
            settings.geocodes_per_instance_per_minute, 60,
        )
    except RuntimeError as error:
        if str(error) == "rate limit exceeded":
            raise HTTPException(429, "rate limit exceeded") from error
        raise
    try:
        result = await request.app.state.geocoder.search(value.query)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(503, "geocoding provider unavailable") from error
    if result is None:
        raise HTTPException(404, "no results found")
    return GeocodeResponse(
        latitude=result.latitude,
        longitude=result.longitude,
        display_name=result.display_name,
    )
