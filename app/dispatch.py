from typing import Optional
import asyncio
import hashlib
import json
import time
import logging
from collections.abc import Callable

from fastapi import HTTPException

from app.audit_store import AuditStore
from app.config_store import ConfigStore
from app.fh2 import FH2Client, build_fh2_payload
from app.idempotency import IdempotencyStore
from app.schemas import DispatchRequest, DispatchResult, FH2Response, StoredFH2Config
from app.security import SlidingWindowLimiter
from app.settings import Settings


ClientFactory = Callable[[float], FH2Client]
logger = logging.getLogger(__name__)


def _fingerprint(request: DispatchRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


class DispatchService:
    def __init__(
        self,
        config_store: Optional[ConfigStore],
        audit_store: AuditStore,
        idempotency_store: IdempotencyStore,
        limiter: SlidingWindowLimiter,
        settings: Settings,
        fh2_client_factory: Optional[ClientFactory] = None,
    ):
        if settings.dispatch_concurrency_per_project <= 0:
            raise ValueError("project dispatch concurrency must be positive")
        self.config_store = config_store
        self.audit_store = audit_store
        self.idempotency_store = idempotency_store
        self.limiter = limiter
        self.settings = settings
        self.fh2_client_factory = fh2_client_factory or FH2Client
        self.project_semaphores: dict[str, asyncio.Semaphore] = {}

    def _load_config(self) -> StoredFH2Config:
        if self.config_store is None:
            raise HTTPException(503, "FH2 configuration is incomplete")
        try:
            config = self.config_store.load()
        except ValueError as error:
            raise HTTPException(503, "FH2 configuration is unavailable") from error
        if config is None:
            raise HTTPException(503, "FH2 configuration is incomplete")
        return config

    def _check_rate_limits(self, actor: str, project_uuid: str) -> None:
        checks = (
            (
                "dispatch-user",
                actor,
                self.settings.dispatches_per_user_per_minute,
            ),
            (
                "dispatch-instance",
                "instance",
                self.settings.dispatches_per_instance_per_minute,
            ),
            (
                "dispatch-project",
                project_uuid,
                self.settings.dispatches_per_project_per_minute,
            ),
        )
        try:
            for scope, key, limit in checks:
                self.limiter.check(scope, key, limit, 60)
        except RuntimeError as error:
            if str(error) == "rate limit exceeded":
                raise HTTPException(429, "rate limit exceeded") from error
            raise

    def _project_semaphore(self, project_uuid: str) -> asyncio.Semaphore:
        semaphore = self.project_semaphores.get(project_uuid)
        if semaphore is None:
            semaphore = asyncio.Semaphore(
                self.settings.dispatch_concurrency_per_project
            )
            self.project_semaphores[project_uuid] = semaphore
        return semaphore

    async def submit(
        self,
        request: DispatchRequest,
        actor: str,
        idempotency_key: str,
    ) -> DispatchResult:
        config = self._load_config()
        if (
            self.settings.live_dispatch_enabled
            and not self.settings.fh2_contract_verified
        ):
            raise HTTPException(503, "FH2 contract is not verified")

        self._check_rate_limits(actor, config.project_uuid)
        semaphore = self._project_semaphore(config.project_uuid)
        async with semaphore:
            reservation = self.idempotency_store.reserve(
                idempotency_key, request.incident_id, _fingerprint(request)
            )
            if reservation.state == "completed":
                if reservation.result is None:
                    raise RuntimeError("completed idempotency result is missing")
                return DispatchResult.model_validate(
                    {**reservation.result, "replayed": True}
                )
            if reservation.state == "processing":
                raise HTTPException(409, "request processing")
            if reservation.state == "conflict":
                raise HTTPException(409, "idempotency conflict")
            if reservation.state != "created" or reservation.generation is None:
                raise RuntimeError("invalid idempotency reservation")

            generation = reservation.generation
            sensitive_values = tuple(
                v for v in (
                    config.user_token,
                    config.project_uuid,
                    config.workflow_uuid,
                    config.creator_id,
                ) if v is not None
            )
            audit_id = self.audit_store.create_pending(
                request,
                actor,
                idempotency_key,
                config.region,
                sensitive_values,
            )
            started = time.monotonic()
            if self.settings.live_dispatch_enabled:
                client = self.fh2_client_factory(
                    self.settings.fh2_timeout_seconds
                )
                try:
                    response = await client.send(
                        config, build_fh2_payload(request, config)
                    )
                except Exception:
                    logger.exception("unexpected FH2 request failure")
                    response = FH2Response(
                        outcome="indeterminate",
                        body={"detail": "upstream request failed"},
                        error_category="unexpected",
                    )
            else:
                response = FH2Response(
                    outcome="success",
                    http_status=200,
                    body={"accepted": True, "mock": True},
                )

            result = DispatchResult(
                **response.model_dump(),
                incident_id=request.incident_id,
                audit_id=audit_id,
            )
            duration_ms = max(0, round((time.monotonic() - started) * 1000))
            self.audit_store.complete(
                audit_id, result, duration_ms, sensitive_values
            )
            try:
                self.idempotency_store.complete(
                    idempotency_key,
                    generation,
                    result,
                    sensitive_values,
                )
            except RuntimeError as error:
                if str(error) == "stale idempotency reservation":
                    raise HTTPException(
                        409, "stale idempotency reservation"
                    ) from error
                raise
            return result
