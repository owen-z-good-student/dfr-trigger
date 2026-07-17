import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import SplitResult, urlsplit

from fastapi import HTTPException, Request


CSRF_TOKEN_MAX_AGE_SECONDS = 3600
MAX_LIMITER_KEYS = 10_000


def _constant_time_ascii_equal(left: str, right: str) -> bool:
    try:
        return hmac.compare_digest(left.encode("ascii"), right.encode("ascii"))
    except (AttributeError, UnicodeEncodeError):
        return False


def create_csrf_token(secret: str, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else now
    nonce = secrets.token_urlsafe(24)
    body = f"{issued}.{nonce}"
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_csrf_token(token: str, secret: str, now: int | None = None) -> bool:
    try:
        issued_text, nonce, signature = token.split(".", 2)
        issued = int(issued_text)
    except (AttributeError, ValueError):
        return False
    body = f"{issued}.{nonce}"
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    current = int(time.time()) if now is None else now
    age = current - issued
    return (
        0 <= age <= CSRF_TOKEN_MAX_AGE_SECONDS
        and _constant_time_ascii_equal(signature, expected)
    )


def issue_csrf_token(request: Request) -> str:
    return create_csrf_token(request.app.state.settings.csrf_secret)


def _split_url(value: str) -> SplitResult | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
        or parsed.netloc.endswith(":")
    ):
        return None
    return parsed


def _origin(value: str, *, origin_header: bool) -> tuple[str, str, int] | None:
    parsed = _split_url(value)
    if parsed is None or parsed.fragment:
        return None
    if origin_header and (parsed.path or parsed.query):
        return None
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def require_state_change(request: Request, *, now: int | None = None) -> None:
    settings = request.app.state.settings
    public_origin = _origin(settings.public_origin, origin_header=True)
    if public_origin is None:
        raise HTTPException(503, "public origin is invalid")
    if _origin(request.headers.get("origin", ""), origin_header=True) != public_origin:
        raise HTTPException(403, "invalid origin")
    if _origin(request.headers.get("referer", ""), origin_header=False) != public_origin:
        raise HTTPException(403, "invalid referer")

    cookie = request.cookies.get("dfr_csrf")
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not _constant_time_ascii_equal(cookie, header):
        raise HTTPException(403, "invalid csrf token")
    if not verify_csrf_token(header, settings.csrf_secret, now=now):
        raise HTTPException(403, "expired csrf token")


def trusted_actor(request: Request) -> str:
    settings = request.app.state.settings
    if not settings.live_dispatch_enabled:
        return "mock-user"

    header_name = settings.trusted_identity_header
    if not header_name:
        raise HTTPException(503, "trusted identity is not configured")

    cidrs = [item.strip() for item in settings.trusted_proxy_cidrs.split(",") if item.strip()]
    if not cidrs:
        raise HTTPException(503, "trusted proxy is not configured")
    try:
        networks = [ipaddress.ip_network(item) for item in cidrs]
    except ValueError:
        raise HTTPException(503, "trusted proxy is invalid") from None

    client = request.client
    try:
        client_ip = ipaddress.ip_address(client.host if client else "")
    except ValueError:
        raise HTTPException(403, "untrusted proxy") from None
    if not any(client_ip in network for network in networks):
        raise HTTPException(403, "untrusted proxy")

    actor = request.headers.get(header_name)
    if (
        not actor
        or not actor.strip()
        or len(actor) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in actor)
    ):
        raise HTTPException(403, "missing trusted identity")
    return actor


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.events: dict[tuple[str, str], deque[float]] = {}
        self.expirations: dict[tuple[str, str], float] = {}
        self.max_keys = MAX_LIMITER_KEYS
        self.lock = threading.Lock()

    def _remove_expired_keys(self, now: float) -> None:
        expired = [
            bucket_key
            for bucket_key, expires_at in self.expirations.items()
            if expires_at <= now
        ]
        for bucket_key in expired:
            self.events.pop(bucket_key, None)
            self.expirations.pop(bucket_key, None)

    def check(self, scope: str, key: str, limit: int, window_seconds: int) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        with self.lock:
            now = self.clock()
            bucket_key = (scope, key)
            if bucket_key not in self.events and len(self.events) >= self.max_keys:
                self._remove_expired_keys(now)
                if len(self.events) >= self.max_keys:
                    raise RuntimeError("rate limit exceeded")
            bucket = self.events.setdefault(bucket_key, deque())
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                self.expirations[bucket_key] = max(
                    self.expirations.get(bucket_key, 0),
                    bucket[-1] + window_seconds,
                )
                raise RuntimeError("rate limit exceeded")
            bucket.append(now)
            self.expirations[bucket_key] = max(
                self.expirations.get(bucket_key, 0), now + window_seconds
            )
