import base64
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import (
    SlidingWindowLimiter,
    create_csrf_token,
    require_state_change,
    trusted_actor,
    verify_csrf_token,
)
from app.settings import Settings


def make_request(
    settings: Settings,
    *,
    headers: dict[str, str] | None = None,
    client_host: str | None = "127.0.0.1",
) -> Request:
    app = FastAPI()
    app.state.settings = settings
    client = (client_host, 50000) if client_host is not None else None
    scope = {
        "type": "http",
        "app": app,
        "client": client,
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ],
    }
    return Request(scope)


def csrf_headers(secret: str, origin: str, referer: str) -> dict[str, str]:
    token = create_csrf_token(secret, now=1_700_000_000)
    return {
        "origin": origin,
        "referer": referer,
        "x-csrf-token": token,
        "cookie": f"dfr_csrf={token}",
    }


def synthetic_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_signed_csrf_token_detects_tampering_and_time_bounds():
    token = create_csrf_token("secret", now=1_700_000_000)

    assert verify_csrf_token(token, "secret", now=1_700_000_100)
    assert verify_csrf_token(token, "secret", now=1_700_003_600)
    assert not verify_csrf_token(token + "x", "secret", now=1_700_000_100)
    assert not verify_csrf_token(token, "secret", now=1_700_003_601)
    assert not verify_csrf_token(token, "secret", now=1_699_999_999)
    assert not verify_csrf_token("malformed", "secret", now=1_700_000_100)


def test_csrf_token_uses_explicit_zero_timestamp():
    token = create_csrf_token("secret", now=0)

    assert token.startswith("0.")
    assert verify_csrf_token(token, "secret", now=0)


def test_verify_csrf_token_rejects_non_ascii_input():
    assert not verify_csrf_token("1700000000.é.é", "secret", now=1_700_000_100)


def test_state_change_accepts_matching_origin_referer_and_token():
    settings = Settings(csrf_secret="secret", public_origin="https://app.example")
    request = make_request(
        settings,
        headers=csrf_headers(
            "secret", "https://app.example", "https://app.example/dispatch?id=1"
        ),
    )

    require_state_change(request, now=1_700_000_100)


@pytest.mark.parametrize(
    ("origin", "referer", "detail"),
    [
        ("https://app.example.evil", "https://app.example/", "invalid origin"),
        ("https://app.example/path", "https://app.example/", "invalid origin"),
        ("https://app.example", "https://app.example.evil/", "invalid referer"),
        ("https://app.example", "https://user@app.example/", "invalid referer"),
        ("https://app.example", "", "invalid referer"),
    ],
)
def test_state_change_rejects_non_exact_origin_or_referer(
    origin: str, referer: str, detail: str
):
    settings = Settings(csrf_secret="secret", public_origin="https://app.example")
    request = make_request(
        settings, headers=csrf_headers("secret", origin, referer)
    )

    with pytest.raises(HTTPException) as exc_info:
        require_state_change(request, now=1_700_000_100)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == detail


@pytest.mark.parametrize(
    "origin",
    [
        "https://app.example:0",
        "https://app.example:",
        "https://app.example:invalid",
        "https://app.example:65536",
    ],
)
def test_state_change_rejects_invalid_explicit_origin_ports(origin: str):
    settings = Settings(csrf_secret="secret", public_origin="https://app.example")
    request = make_request(
        settings,
        headers=csrf_headers("secret", origin, "https://app.example/dispatch"),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_state_change(request, now=1_700_000_100)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "invalid origin"


@pytest.mark.parametrize(
    "public_origin", ["https://app.example:0", "https://app.example:"]
)
def test_state_change_rejects_zero_or_empty_public_origin_port(public_origin: str):
    settings = Settings(csrf_secret="secret", public_origin=public_origin)
    request = make_request(
        settings,
        headers=csrf_headers(
            "secret", "https://app.example", "https://app.example/dispatch"
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_state_change(request, now=1_700_000_100)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "public origin is invalid"


def test_state_change_rejects_matching_non_ascii_csrf_values():
    settings = Settings(csrf_secret="secret", public_origin="https://app.example")
    request = make_request(
        settings,
        headers={
            "origin": "https://app.example",
            "referer": "https://app.example/dispatch",
            "x-csrf-token": "é",
            "cookie": "dfr_csrf=é",
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        require_state_change(request, now=1_700_000_100)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "invalid csrf token"


def test_state_change_rejects_mismatched_double_submit_token():
    settings = Settings(csrf_secret="secret", public_origin="https://app.example")
    headers = csrf_headers(
        "secret", "https://app.example", "https://app.example/dispatch"
    )
    headers["x-csrf-token"] = create_csrf_token("secret", now=1_700_000_000)
    request = make_request(settings, headers=headers)

    with pytest.raises(HTTPException) as exc_info:
        require_state_change(request, now=1_700_000_100)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "invalid csrf token"


def test_mock_actor_is_constant_and_ignores_spoofed_header():
    settings = Settings(
        live_dispatch_enabled=False,
        trusted_identity_header="x-member-id",
        trusted_proxy_cidrs="10.0.0.0/8",
    )
    request = make_request(
        settings,
        headers={"x-member-id": "spoofed-user"},
        client_host="203.0.113.10",
    )

    assert trusted_actor(request) == "mock-user"


def test_live_actor_requires_trusted_proxy_and_identity():
    settings = Settings(
        live_dispatch_enabled=True,
        trusted_identity_header="x-member-id",
        trusted_proxy_cidrs="10.0.0.0/8, 2001:db8::/32",
    )
    request = make_request(
        settings, headers={"x-member-id": "synthetic-user"}, client_host="10.1.2.3"
    )

    assert trusted_actor(request) == "synthetic-user"


@pytest.mark.parametrize(
    ("cidrs", "client_host", "headers", "status_code", "detail"),
    [
        ("", "10.1.2.3", {"x-member-id": "synthetic-user"}, 503, "trusted proxy is not configured"),
        ("invalid", "10.1.2.3", {"x-member-id": "synthetic-user"}, 503, "trusted proxy is invalid"),
        ("10.0.0.0/8", "203.0.113.10", {"x-member-id": "synthetic-user"}, 403, "untrusted proxy"),
        ("10.0.0.0/8", "not-an-ip", {"x-member-id": "synthetic-user"}, 403, "untrusted proxy"),
        ("10.0.0.0/8", None, {"x-member-id": "synthetic-user"}, 403, "untrusted proxy"),
        ("10.0.0.0/8", "10.1.2.3", {}, 403, "missing trusted identity"),
        ("10.0.0.0/8", "10.1.2.3", {"x-member-id": "x" * 257}, 403, "missing trusted identity"),
    ],
)
def test_live_actor_fails_closed(
    cidrs: str,
    client_host: str | None,
    headers: dict[str, str],
    status_code: int,
    detail: str,
):
    settings = Settings(
        live_dispatch_enabled=True,
        trusted_identity_header="x-member-id",
        trusted_proxy_cidrs=cidrs,
    )
    request = make_request(settings, headers=headers, client_host=client_host)

    with pytest.raises(HTTPException) as exc_info:
        trusted_actor(request)

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail == detail


def test_rate_limiter_rejects_sixth_request():
    limiter = SlidingWindowLimiter(clock=lambda: 100.0)
    for _ in range(5):
        limiter.check("dispatch-user", "synthetic-user", 5, 60)

    with pytest.raises(RuntimeError, match="^rate limit exceeded$"):
        limiter.check("dispatch-user", "synthetic-user", 5, 60)


@pytest.mark.parametrize(
    ("limit", "window_seconds"),
    [(0, 60), (-1, 60), (5, 0), (5, -1)],
)
def test_rate_limiter_rejects_non_positive_parameters(limit, window_seconds):
    limiter = SlidingWindowLimiter(clock=lambda: (_ for _ in ()).throw(AssertionError))

    with pytest.raises(
        ValueError, match="^limit and window_seconds must be positive$"
    ):
        limiter.check(
            "dispatch-user", "synthetic-user", limit, window_seconds
        )

    assert limiter.events == {}


def test_rate_limiter_check_is_atomic_across_threads():
    limiter = SlidingWindowLimiter(clock=lambda: 100.0)
    barrier = Barrier(6)

    def attempt() -> bool:
        barrier.wait()
        try:
            limiter.check("dispatch-user", "synthetic-user", 5, 60)
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=6) as executor:
        accepted = list(executor.map(lambda _: attempt(), range(6)))

    assert sum(accepted) == 5


def test_rate_limiter_removes_stale_keys_when_capacity_is_reached():
    now = [100.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0])
    limiter.max_keys = 2
    limiter.check("dispatch-user", "one", 5, 10)
    limiter.check("dispatch-user", "two", 5, 10)

    now[0] = 111.0
    limiter.check("dispatch-user", "three", 5, 10)

    assert set(limiter.events) == {("dispatch-user", "three")}


def test_rate_limiter_bounds_active_key_cardinality():
    limiter = SlidingWindowLimiter(clock=lambda: 100.0)
    limiter.max_keys = 2
    limiter.check("dispatch-user", "one", 5, 60)
    limiter.check("dispatch-user", "two", 5, 60)

    for key in ("three", "four"):
        with pytest.raises(RuntimeError, match="^rate limit exceeded$"):
            limiter.check("dispatch-user", key, 5, 60)

    assert set(limiter.events) == {
        ("dispatch-user", "one"),
        ("dispatch-user", "two"),
    }


def test_bootstrap_sets_non_secure_cookie_for_local_http_and_api_headers(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        csrf_secret="synthetic-secret",
        public_origin="http://testserver",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    assert response.json() == {"mode": "mock"}
    cookie = response.headers["set-cookie"]
    assert "dfr_csrf=" in cookie
    assert "Max-Age=3600" in cookie
    assert "Path=/" in cookie
    assert "SameSite=strict" in cookie
    assert "HttpOnly" not in cookie
    assert "Secure" not in cookie
    assert response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["cache-control"] == "no-store"


def test_bootstrap_sets_secure_cookie_exactly_for_https(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        csrf_secret="synthetic-secret",
        public_origin="https://app.example",
    )

    with TestClient(create_app(settings), base_url="https://app.example") as client:
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_unhandled_api_error_has_security_headers_without_exception_details(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))

    @app.get("/api/synthetic-failure")
    def synthetic_failure():
        raise RuntimeError("synthetic private detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/synthetic-failure")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "synthetic private detail" not in response.text
    assert response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["cache-control"] == "no-store"


def test_live_bootstrap_rejects_spoofed_identity_from_untrusted_client(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        live_dispatch_enabled=True,
        fh2_contract_verified=True,
        dfr_config_key=synthetic_key(),
        csrf_secret="synthetic-secret-that-is-at-least-32-bytes",
        public_origin="https://app.example",
        trusted_identity_header="x-member-id",
        trusted_proxy_cidrs="10.0.0.0/8",
    )

    with TestClient(
        create_app(settings),
        base_url="https://app.example",
        client=("203.0.113.10", 50000),
    ) as client:
        response = client.get(
            "/api/bootstrap", headers={"x-member-id": "spoofed-user"}
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "untrusted proxy"}
