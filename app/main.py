import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import router as api_router
from app.audit_store import AuditStore
from app.config_store import ConfigStore
from app.crypto import ValueCipher
from app.db import Database
from app.dispatch import DispatchService
from app.idempotency import IdempotencyStore
from app.geocoding import Geocoder
from app.maintenance import cleanup_loop
from app.security import SlidingWindowLimiter, issue_csrf_token, trusted_actor
from app.settings import Settings, get_settings

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(runtime.data_dir / "dfr_trigger.db")
        database.initialize()
        app.state.settings = runtime
        app.state.database = database
        if runtime.dfr_config_key:
            app.state.config_store = ConfigStore(
                database, ValueCipher(runtime.dfr_config_key)
            )
        else:
            app.state.config_store = None
        if runtime.live_dispatch_enabled:
            missing = []
            if not runtime.fh2_contract_verified:
                missing.append("fh2_contract_verified")
            if not runtime.dfr_config_key:
                missing.append("dfr_config_key")
            if (
                runtime.csrf_secret == "mock-only-change-before-live"
                or len(runtime.csrf_secret) < 32
            ):
                missing.append("csrf_secret")
            if not runtime.public_origin.startswith("https://") and not runtime.dev_mode:
                missing.append("https_public_origin")
            if not runtime.trusted_identity_header:
                missing.append("trusted_identity_header")
            if not runtime.trusted_proxy_cidrs:
                missing.append("trusted_proxy_cidrs")
            if missing:
                raise RuntimeError(
                    "live mode release gates failed: " + ", ".join(missing)
                )
        audit_store = AuditStore(database)
        idempotency_store = IdempotencyStore(database, runtime.log_retention_days)
        limiter = SlidingWindowLimiter()
        app.state.audit_store = audit_store
        app.state.idempotency_store = idempotency_store
        app.state.limiter = limiter
        app.state.geocoder = Geocoder(
            timeout_seconds=runtime.geocoding_timeout_seconds
        )
        app.state.dispatch_service = DispatchService(
            app.state.config_store,
            audit_store,
            idempotency_store,
            limiter,
            runtime,
        )
        audit_store.cleanup(runtime.log_retention_days)
        idempotency_store.cleanup()
        cleanup_task = asyncio.create_task(
            cleanup_loop(audit_store, idempotency_store, runtime.log_retention_days)
        )
        try:
            yield
        finally:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    app = FastAPI(title="DFR Trigger", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(api_router)

    @app.middleware("http")
    async def add_api_security_headers(request: Request, call_next):
        is_api_request = request.url.path.startswith("/api/")
        if runtime.live_dispatch_enabled and request.url.path != "/api/health":
            try:
                trusted_actor(request)
            except HTTPException as error:
                return JSONResponse(
                    status_code=error.status_code,
                    content={"detail": error.detail},
                )
        try:
            response = await call_next(request)
        except Exception:
            if not is_api_request:
                raise
            response = JSONResponse(
                status_code=500, content={"detail": "internal server error"}
            )
        if is_api_request:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' https://tile.openstreetmap.org data:; "
                "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": runtime.mode}

    @app.get("/api/bootstrap")
    def bootstrap(request: Request, response: Response) -> dict[str, str]:
        trusted_actor(request)
        response.set_cookie(
            key="dfr_csrf",
            value=issue_csrf_token(request),
            max_age=3600,
            path="/",
            secure=urlsplit(runtime.public_origin).scheme.lower() == "https",
            httponly=False,
            samesite="strict",
        )
        return {"mode": runtime.mode}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"mode": runtime.mode},
        )

    return app


app = create_app()
