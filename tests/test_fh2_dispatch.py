import asyncio
import base64

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.dispatch import DispatchService
from app.fh2 import FH2Client, build_fh2_payload
from app.idempotency import Reservation
from app.main import create_app
from app.schemas import ConfigWrite, DispatchRequest, DispatchResult, FH2Response, StoredFH2Config
from app.security import SlidingWindowLimiter
from app.settings import Settings


WORKFLOW_URL = "https://es-flight-api-eu.djigate.com/openapi/v0.1/workflow"
SENSITIVE_VALUES = (
    "secret-token",
    "project-uuid",
    "workflow-uuid",
    "creator-123",
)


def dispatch_request(**overrides) -> DispatchRequest:
    values = {
        "incident_id": "INC-20260714-0001",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "priority": 5,
        "incident_type": "Fire",
        "description": "Synthetic integration test",
    }
    values.update(overrides)
    return DispatchRequest(**values)


def stored_config() -> StoredFH2Config:
    return StoredFH2Config(
        region="eu",
        user_token="secret-token",
        project_uuid="project-uuid",
        workflow_uuid="workflow-uuid",
        creator_id="creator-123",
    )


def encoded_key() -> str:
    return base64.urlsafe_b64encode(b"s" * 32).decode()


class ConfigStub:
    def __init__(self, value=stored_config()):
        self.value = value
        self.calls = 0

    def load(self):
        self.calls += 1
        return self.value


class AuditSpy:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.pending_calls = []
        self.complete_calls = []

    def create_pending(
        self, request, actor, idempotency_key, region, sensitive_values
    ):
        self.events.append("pending")
        self.pending_calls.append(
            (request, actor, idempotency_key, region, sensitive_values)
        )
        return f"audit-{len(self.pending_calls)}"

    def complete(self, audit_id, result, duration_ms, sensitive_values):
        self.events.append("audit-complete")
        self.complete_calls.append(
            (audit_id, result, duration_ms, sensitive_values)
        )


class IdempotencySpy:
    def __init__(self, reservations=None, complete_error=None):
        self.reservations = list(reservations or [])
        self.complete_error = complete_error
        self.reserve_calls = []
        self.complete_calls = []

    def reserve(self, key, incident_id, fingerprint):
        self.reserve_calls.append((key, incident_id, fingerprint))
        if self.reservations:
            return self.reservations.pop(0)
        return Reservation(
            "created", generation=f"generation-{len(self.reserve_calls)}"
        )

    def complete(self, key, generation, result, sensitive_values):
        self.complete_calls.append((key, generation, result, sensitive_values))
        if self.complete_error is not None:
            raise self.complete_error


class LimiterSpy:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def check(self, scope, key, limit, window_seconds):
        self.calls.append((scope, key, limit, window_seconds))
        if self.error is not None:
            raise self.error


class ClientSpy:
    def __init__(self, response=None, events=None):
        self.response = response or FH2Response(
            outcome="success", http_status=200, body={"synthetic": True}
        )
        self.events = events if events is not None else []
        self.calls = []

    async def send(self, config, payload):
        self.events.append("send")
        self.calls.append((config, payload))
        return self.response


def service(
    *,
    config_store=None,
    audit_store=None,
    idempotency_store=None,
    limiter=None,
    settings=None,
    fh2_client_factory=None,
):
    return DispatchService(
        config_store=config_store or ConfigStub(),
        audit_store=audit_store or AuditSpy(),
        idempotency_store=idempotency_store or IdempotencySpy(),
        limiter=limiter or LimiterSpy(),
        settings=settings or Settings(live_dispatch_enabled=False),
        fh2_client_factory=fh2_client_factory,
    )


def test_dispatch_schema_forbids_unknown_fields_and_invalid_other_combinations():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        dispatch_request(unknown="synthetic")

    with pytest.raises(ValidationError, match="custom_incident_type is required"):
        dispatch_request(incident_type="Other")

    with pytest.raises(ValidationError, match="custom_incident_type requires Other"):
        dispatch_request(custom_incident_type="Synthetic custom type")


def test_configuration_write_schema_forbids_unknown_fields():
    values = stored_config().model_dump()
    values["base_url"] = "https://attacker.invalid"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ConfigWrite(**values)


def test_payload_uses_only_official_fields_in_stable_order():
    request = dispatch_request(
        incident_type="Other",
        custom_incident_type="Synthetic Hazard",
        location="Synthetic Test Site",
        operator_name="Synthetic Operator",
        caller_phone="+33 000 000 000",
        description="Synthetic description",
    )

    payload = build_fh2_payload(request, stored_config())

    assert payload == {
        "workflow_uuid": "workflow-uuid",
        "trigger_type": 0,
        "name": "Emergency Alert - [INC-20260714-0001]",
        "params": {
            "creator": "creator-123",
            "latitude": 48.8566,
            "longitude": 2.3522,
            "level": 5,
            "desc": (
                "Incident Type: Synthetic Hazard\n"
                "Location: Synthetic Test Site\n"
                "Operator: Synthetic Operator\n"
                "Caller: +33 000 000 000\n"
                "Description: Synthetic description\n"
                "Incident ID: INC-20260714-0001"
            ),
        },
    }


def test_payload_omits_empty_optional_description_lines():
    request = dispatch_request(
        incident_type=None,
        description=None,
        location="",
        operator_name=None,
        caller_phone=None,
    )

    payload = build_fh2_payload(request, stored_config())

    assert payload["params"]["desc"] == "Incident ID: INC-20260714-0001"


@pytest.mark.asyncio
async def test_fh2_adapter_uses_fixed_url_exact_headers_and_json(respx_mock):
    route = respx_mock.post(WORKFLOW_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "message": "accepted"})
    )
    payload = build_fh2_payload(dispatch_request(), stored_config())

    result = await FH2Client(timeout_seconds=0.1).send(stored_config(), payload)

    assert result == FH2Response(
        outcome="success",
        http_status=200,
        body={"code": 0, "message": "accepted"},
    )
    assert route.call_count == 1
    sent = route.calls[0].request
    assert sent.headers["Content-Type"] == "application/json"
    assert sent.headers["X-User-Token"] == "secret-token"
    assert sent.headers["x-project-uuid"] == "project-uuid"
    assert sent.url == httpx.URL(WORKFLOW_URL)


@pytest.mark.parametrize("timeout_type", [httpx.ReadTimeout, httpx.WriteTimeout])
@pytest.mark.asyncio
async def test_timeout_is_indeterminate_and_not_retried(respx_mock, timeout_type):
    route = respx_mock.post(WORKFLOW_URL).mock(
        side_effect=timeout_type("synthetic timeout")
    )

    result = await FH2Client(timeout_seconds=0.1).send(
        stored_config(), build_fh2_payload(dispatch_request(), stored_config())
    )

    assert result.outcome == "indeterminate"
    assert result.error_category == "timeout"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_connection_failure_before_write_is_failure_and_not_retried(respx_mock):
    route = respx_mock.post(WORKFLOW_URL).mock(
        side_effect=httpx.ConnectError("synthetic connection failure")
    )

    result = await FH2Client(timeout_seconds=0.1).send(
        stored_config(), build_fh2_payload(dispatch_request(), stored_config())
    )

    assert result.outcome == "failure"
    assert result.error_category == "connection"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_non_json_http_failure_body_is_bounded_and_redirect_is_not_followed(
    respx_mock,
):
    route = respx_mock.post(WORKFLOW_URL).mock(
        return_value=httpx.Response(307, content=b"x" * 100_000)
    )

    result = await FH2Client(timeout_seconds=0.1).send(
        stored_config(), build_fh2_payload(dispatch_request(), stored_config())
    )

    assert result.outcome == "failure"
    assert result.http_status == 307
    assert isinstance(result.body, str)
    assert len(result.body.encode()) < 5_000
    assert result.body.endswith("[TRUNCATED]")
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_large_json_fh2_response_is_bounded_before_parsing(respx_mock):
    route = respx_mock.post(WORKFLOW_URL).mock(
        return_value=httpx.Response(200, json={"detail": "x" * 70_000})
    )
    result = await FH2Client(timeout_seconds=0.1).send(
        stored_config(), build_fh2_payload(dispatch_request(), stored_config())
    )
    assert route.call_count == 1
    assert len(str(result.body).encode()) <= 65_536
    assert "[TRUNCATED]" in str(result.body)


@pytest.mark.asyncio
async def test_mock_dispatch_enforces_all_limits_and_passes_sensitive_values():
    audit = AuditSpy()
    idempotency = IdempotencySpy()
    limiter = LimiterSpy()
    dispatch = service(
        audit_store=audit,
        idempotency_store=idempotency,
        limiter=limiter,
    )

    result = await dispatch.submit(
        dispatch_request(), "synthetic-actor", "synthetic_key_0001"
    )

    assert result == DispatchResult(
        incident_id="INC-20260714-0001",
        audit_id="audit-1",
        outcome="success",
        http_status=200,
        body={"accepted": True, "mock": True},
    )
    assert limiter.calls == [
        ("dispatch-user", "synthetic-actor", 5, 60),
        ("dispatch-instance", "instance", 20, 60),
        ("dispatch-project", "project-uuid", 20, 60),
    ]
    assert audit.pending_calls[0][-1] == SENSITIVE_VALUES
    assert audit.complete_calls[0][-1] == SENSITIVE_VALUES
    assert idempotency.complete_calls[0][0:2] == (
        "synthetic_key_0001",
        "generation-1",
    )
    assert idempotency.complete_calls[0][-1] == SENSITIVE_VALUES
    assert len(idempotency.reserve_calls[0][2]) == 64


@pytest.mark.asyncio
async def test_pending_audit_precedes_verified_live_client_selection_and_send():
    events = []
    audit = AuditSpy(events)
    client = ClientSpy(events=events)

    def client_factory(timeout_seconds):
        assert timeout_seconds == 0.25
        events.append("client-selected")
        return client

    dispatch = service(
        audit_store=audit,
        settings=Settings(
            live_dispatch_enabled=True,
            fh2_contract_verified=True,
            fh2_timeout_seconds=0.25,
        ),
        fh2_client_factory=client_factory,
    )

    result = await dispatch.submit(
        dispatch_request(), "synthetic-actor", "synthetic_key_0002"
    )

    assert result.outcome == "success"
    assert events == ["pending", "client-selected", "send", "audit-complete"]
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_live_dispatch_is_refused_until_contract_is_verified():
    selected = []

    def client_factory(timeout_seconds):
        selected.append(timeout_seconds)
        return ClientSpy()

    dispatch = service(
        settings=Settings(
            live_dispatch_enabled=True,
            fh2_contract_verified=False,
        ),
        fh2_client_factory=client_factory,
    )

    with pytest.raises(HTTPException) as exc_info:
        await dispatch.submit(
            dispatch_request(), "synthetic-actor", "synthetic_key_0003"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "FH2 contract is not verified"
    assert selected == []


@pytest.mark.asyncio
async def test_completed_replay_returns_stored_result_without_new_side_effects():
    stored = DispatchResult(
        incident_id="INC-20260714-0001",
        audit_id="audit-existing",
        outcome="success",
        http_status=200,
        body={"accepted": True},
    ).model_dump(mode="json")
    audit = AuditSpy()
    idempotency = IdempotencySpy(
        [Reservation("completed", result=stored, generation="old-generation")]
    )
    dispatch = service(audit_store=audit, idempotency_store=idempotency)

    result = await dispatch.submit(
        dispatch_request(), "synthetic-actor", "synthetic_key_0004"
    )

    assert result.replayed is True
    assert result.audit_id == "audit-existing"
    assert audit.pending_calls == []
    assert audit.complete_calls == []
    assert idempotency.complete_calls == []


@pytest.mark.parametrize(
    ("state", "detail"),
    [
        ("processing", "request processing"),
        ("conflict", "idempotency conflict"),
    ],
)
@pytest.mark.asyncio
async def test_processing_and_conflict_reservations_map_to_409(state, detail):
    idempotency = IdempotencySpy([Reservation(state)])
    dispatch = service(idempotency_store=idempotency)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch.submit(
            dispatch_request(), "synthetic-actor", "synthetic_key_0005"
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == detail
    assert idempotency.complete_calls == []


@pytest.mark.asyncio
async def test_stale_generation_maps_to_409_without_retry_or_re_read():
    client = ClientSpy()
    idempotency = IdempotencySpy(
        complete_error=RuntimeError("stale idempotency reservation")
    )
    dispatch = service(
        idempotency_store=idempotency,
        settings=Settings(
            live_dispatch_enabled=True,
            fh2_contract_verified=True,
        ),
        fh2_client_factory=lambda timeout_seconds: client,
    )

    with pytest.raises(HTTPException) as exc_info:
        await dispatch.submit(
            dispatch_request(), "synthetic-actor", "synthetic_key_0006"
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "stale idempotency reservation"
    assert len(client.calls) == 1
    assert len(idempotency.reserve_calls) == 1
    assert len(idempotency.complete_calls) == 1


@pytest.mark.asyncio
async def test_unexpected_idempotency_runtime_error_propagates():
    idempotency = IdempotencySpy(
        complete_error=RuntimeError("synthetic unexpected storage failure")
    )
    dispatch = service(idempotency_store=idempotency)

    with pytest.raises(RuntimeError, match="synthetic unexpected storage failure"):
        await dispatch.submit(
            dispatch_request(), "synthetic-actor", "synthetic_key_0007"
        )


@pytest.mark.asyncio
async def test_unexpected_upstream_error_finalizes_without_retry():
    class FailingClient(ClientSpy):
        async def send(self, config, payload):
            self.calls.append((config, payload))
            raise RuntimeError("synthetic protocol failure")

    audit = AuditSpy()
    idempotency = IdempotencySpy()
    client = FailingClient()
    dispatch = service(
        audit_store=audit,
        idempotency_store=idempotency,
        settings=Settings(live_dispatch_enabled=True, fh2_contract_verified=True),
        fh2_client_factory=lambda timeout_seconds: client,
    )
    result = await dispatch.submit(
        dispatch_request(), "synthetic-actor", "synthetic_key_unexpected"
    )
    assert result.outcome == "indeterminate"
    assert result.error_category == "unexpected"
    assert len(client.calls) == 1
    assert audit.complete_calls[0][1].outcome == "indeterminate"
    assert idempotency.complete_calls[0][2].outcome == "indeterminate"


@pytest.mark.asyncio
async def test_missing_configuration_fails_before_reservation():
    idempotency = IdempotencySpy()
    dispatch = service(
        config_store=ConfigStub(None), idempotency_store=idempotency
    )

    with pytest.raises(HTTPException) as exc_info:
        await dispatch.submit(
            dispatch_request(), "synthetic-actor", "synthetic_key_0008"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "FH2 configuration is incomplete"
    assert idempotency.reserve_calls == []


@pytest.mark.parametrize(
    "limited_setting",
    [
        "dispatches_per_user_per_minute",
        "dispatches_per_instance_per_minute",
        "dispatches_per_project_per_minute",
    ],
)
@pytest.mark.asyncio
async def test_each_dispatch_rate_limit_maps_to_429(limited_setting):
    values = {
        "dispatches_per_user_per_minute": 10,
        "dispatches_per_instance_per_minute": 10,
        "dispatches_per_project_per_minute": 10,
    }
    values[limited_setting] = 1
    dispatch = service(
        limiter=SlidingWindowLimiter(clock=lambda: 100.0),
        settings=Settings(**values),
    )

    await dispatch.submit(
        dispatch_request(), "synthetic-actor", "synthetic_key_0009"
    )
    with pytest.raises(HTTPException) as exc_info:
        await dispatch.submit(
            dispatch_request(incident_id="INC-20260714-0002"),
            "synthetic-actor",
            "synthetic_key_0010",
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "rate limit exceeded"


@pytest.mark.asyncio
async def test_project_concurrency_serializes_live_sends():
    class ConcurrentClient(ClientSpy):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.maximum_active = 0

        async def send(self, config, payload):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            self.calls.append((config, payload))
            return self.response

    client = ConcurrentClient()
    dispatch = service(
        limiter=SlidingWindowLimiter(clock=lambda: 100.0),
        settings=Settings(
            live_dispatch_enabled=True,
            fh2_contract_verified=True,
            dispatches_per_user_per_minute=10,
            dispatches_per_instance_per_minute=10,
            dispatches_per_project_per_minute=10,
            dispatch_concurrency_per_project=1,
        ),
        fh2_client_factory=lambda timeout_seconds: client,
    )

    results = await asyncio.gather(
        dispatch.submit(
            dispatch_request(incident_id="INC-20260714-0011"),
            "synthetic-actor",
            "synthetic_key_0011",
        ),
        dispatch.submit(
            dispatch_request(incident_id="INC-20260714-0012"),
            "synthetic-actor",
            "synthetic_key_0012",
        ),
    )

    assert [result.outcome for result in results] == ["success", "success"]
    assert client.maximum_active == 1
    assert len(client.calls) == 2


def csrf_headers(client: TestClient) -> dict[str, str]:
    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    token = client.cookies.get("dfr_csrf")
    assert token
    return {
        "origin": "http://testserver",
        "referer": "http://testserver/dispatch",
        "x-csrf-token": token,
    }


def api_config() -> dict:
    return stored_config().model_dump(mode="json")


def test_protected_config_dispatch_and_log_api_mock_flow(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            dfr_config_key=encoded_key(),
            csrf_secret="synthetic-csrf-secret",
            public_origin="http://testserver",
        )
    )

    with TestClient(app) as client:
        headers = csrf_headers(client)
        saved = client.put("/api/config", headers=headers, json=api_config())
        status = client.get("/api/config")
        tested = client.post("/api/config/test", headers=headers)
        dispatched = client.post(
            "/api/dispatch",
            headers={**headers, "Idempotency-Key": "synthetic_api_key_0001"},
            json=dispatch_request().model_dump(mode="json"),
        )
        replayed = client.post(
            "/api/dispatch",
            headers={**headers, "Idempotency-Key": "synthetic_api_key_0001"},
            json=dispatch_request().model_dump(mode="json"),
        )
        logs = client.get("/api/logs")

    expected_status = {
        "region": "eu",
        "token_configured": True,
        "project_uuid_suffix": "t-uuid",
        "workflow_uuid_suffix": "w-uuid",
        "creator_id_suffix": "or-123",
    }
    assert saved.status_code == 200
    assert saved.json() == expected_status
    assert status.status_code == 200
    assert status.json() == expected_status
    assert tested.status_code == 200
    assert tested.json() == {"valid": True, "fh2_request_sent": False}
    assert dispatched.status_code == 200
    assert dispatched.json()["outcome"] == "success"
    assert dispatched.json()["replayed"] is False
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert logs.status_code == 200
    assert len(logs.json()["items"]) == 1
    combined = " ".join(
        response.text for response in (saved, status, tested, dispatched, replayed, logs)
    )
    assert "secret-token" not in combined
    assert "project-uuid" not in combined
    assert "workflow-uuid" not in combined
    assert "creator-123" not in combined


@pytest.mark.parametrize(
    ("method", "path", "json_body", "headers"),
    [
        ("put", "/api/config", api_config(), {}),
        ("post", "/api/config/test", None, {}),
        (
            "post",
            "/api/dispatch",
            dispatch_request().model_dump(mode="json"),
            {"Idempotency-Key": "synthetic_api_key_0002"},
        ),
    ],
)
def test_state_changing_api_routes_require_csrf(
    tmp_path, method, path, json_body, headers
):
    app = create_app(
        Settings(data_dir=tmp_path, dfr_config_key=encoded_key())
    )

    with TestClient(app) as client:
        response = client.request(method, path, json=json_body, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "invalid origin"}


@pytest.mark.parametrize("path", ["/api/config", "/api/logs"])
def test_read_api_routes_require_trusted_actor_in_live_mode(tmp_path, path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            live_dispatch_enabled=True,
            fh2_contract_verified=True,
            dfr_config_key=encoded_key(),
            csrf_secret="synthetic-secret-that-is-at-least-32-bytes",
            public_origin="https://app.example",
            trusted_identity_header="x-member-id",
            trusted_proxy_cidrs="10.0.0.0/8",
        ),
    )

    with TestClient(
        app,
        base_url="https://app.example",
        client=("203.0.113.10", 50000),
    ) as client:
        response = client.get(path, headers={"x-member-id": "spoofed-user"})

    assert response.status_code == 403
    assert response.json() == {"detail": "untrusted proxy"}


def test_config_api_fails_closed_without_encryption_store(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, dfr_config_key=None))

    with TestClient(app) as client:
        response = client.get("/api/config")

    assert response.status_code == 503
    assert response.json() == {"detail": "configuration store is unavailable"}


def test_dispatch_api_rejects_invalid_key_and_unknown_request_field(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            dfr_config_key=encoded_key(),
            csrf_secret="synthetic-csrf-secret",
            public_origin="http://testserver",
        )
    )

    with TestClient(app) as client:
        headers = csrf_headers(client)
        assert client.put("/api/config", headers=headers, json=api_config()).status_code == 200
        invalid_key = client.post(
            "/api/dispatch",
            headers={**headers, "Idempotency-Key": "short"},
            json=dispatch_request().model_dump(mode="json"),
        )
        body = dispatch_request().model_dump(mode="json")
        body["unexpected"] = "synthetic"
        extra_field = client.post(
            "/api/dispatch",
            headers={**headers, "Idempotency-Key": "synthetic_api_key_0003"},
            json=body,
        )

    assert invalid_key.status_code == 422
    assert extra_field.status_code == 422


def test_logs_api_maps_invalid_cursor_to_422(tmp_path):
    app = create_app(
        Settings(data_dir=tmp_path, dfr_config_key=encoded_key())
    )

    with TestClient(app) as client:
        response = client.get("/api/logs?cursor=not-a-valid-cursor!")

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid audit cursor"}
