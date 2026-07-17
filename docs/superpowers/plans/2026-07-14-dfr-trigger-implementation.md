# DFR Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a FlightHub 2-styled DFR trigger that safely submits documented Triggered Workflow requests to an authorized FH2 Public Cloud test project.

**Architecture:** A single FastAPI application serves Jinja2 HTML and static JavaScript, owns encrypted FH2 configuration, writes seven-day SQLite audit records, and calls FH2 through one allowlisted adapter. DreamCoder provides the instance-member access gate; application-level CSRF, trusted-proxy identity checks, rate limits, idempotency, and fail-closed audit behavior protect state-changing routes.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Pydantic v2, HTTPX, AES-256-GCM from `cryptography`, SQLite, pytest, RESPX, Playwright, Leaflet 1.9.4, Lucide 0.544.0, DreamCoder `publish.yml`, OpenCode Superpowers v6.1.1

## Global Constraints

- Work only in `/home/opencode/vibe-coding/DFR Trigger`; do not modify global OpenCode configuration or the Mac.
- Keep `LIVE_DISPATCH_ENABLED=false` until every release gate in the approved spec passes.
- Target only FlightHub 2 Public Cloud Global and Europe hosts; users cannot enter a URL.
- Preserve official header casing: `X-User-Token` and lowercase `x-project-uuid`.
- Treat `/openapi/v0.1/workflow` as evidence from the existing working trigger, because the current public manual exposes only regional base hosts; verify the final path before live smoke testing.
- Use the actual FlightHub 2-generated Creator ID; the manual sample `1988423428261173248` is placeholder text and must never become a saved default.
- Set `trigger_type` to integer `0`; use WGS84 coordinates and event level `1` through `5`, default `5`.
- Do not automatically retry dispatch after timeout, connection ambiguity, or FH2 `5xx`.
- Store complete business request and response bodies only after recursive secret redaction and a 64 KiB per-value limit.
- Never store or return plaintext tokens, authentication headers, the AES key, or unmasked Project UUID, Workflow UUID, or Creator ID metadata.
- Retain audit and completed idempotency records for seven days.
- Use `49px` collapsed navigation, `131px` expanded navigation, `250px` panel width, `220ms cubic-bezier(0.4, 0, 0.2, 1)` rail animation, and a `150ms` panel-content fade.
- Use Lucide `Drone`, `Wrench`, and `BookOpen` icons at `24px` with a `2px` stroke.
- Preserve one-click dispatch; prevent duplicates with a disabled in-flight button and a server-side unique idempotency key.
- If DreamCoder identity enforcement, trusted identity propagation, secret injection, or persistent storage cannot be proven, deploy Mock mode only.

## File Map

```text
DFR Trigger/
├── .env.example                         # non-secret runtime contract
├── .gitignore                           # excludes secrets, runtime data, caches
├── AGENTS.md                            # project workflow and safety rules
├── opencode.json                        # project-level Superpowers plugin
├── publish.yml                          # DreamCoder backend deployment
├── pyproject.toml                       # runtime and test dependencies
├── uv.lock                              # reproducible Python environment
├── .opencode/
│   ├── package.json                     # OpenCode project plugin dependency
│   └── plugins/superpowers-guard.js     # disables nonessential traffic
├── app/
│   ├── __init__.py
│   ├── main.py                          # application factory and middleware
│   ├── settings.py                      # validated environment settings
│   ├── db.py                            # SQLite schema and connection factory
│   ├── schemas.py                       # HTTP and service data contracts
│   ├── crypto.py                        # AES-GCM value encryption
│   ├── config_store.py                  # encrypted FH2 configuration
│   ├── security.py                      # CSRF, origin, identity, rate limits
│   ├── redaction.py                     # recursive audit sanitization
│   ├── audit_store.py                   # pending/completed audit operations
│   ├── idempotency.py                   # unique request reservation and replay
│   ├── maintenance.py                   # daily seven-day retention cleanup
│   ├── fh2.py                           # fixed-host FH2 request adapter
│   ├── dispatch.py                      # dispatch orchestration
│   ├── geocoding.py                     # fixed-host Nominatim adapter and cache
│   ├── api.py                           # JSON API routes
│   ├── templates/index.html             # application shell and panels
│   └── static/
│       ├── styles.css                   # FH2-inspired visual system
│       └── js/
│           ├── api.js                   # same-origin JSON client and CSRF
│           ├── navigation.js            # rail and panel transitions
│           ├── map.js                   # Leaflet map and coordinate sync
│           ├── dispatch.js              # form state and submission
│           ├── configuration.js         # masked configuration workflow
│           ├── logs.js                  # audit filters and detail rendering
│           └── main.js                  # browser module composition
├── docs/
│   ├── fh2-contract-evidence.md         # verified official/current request evidence
│   └── superpowers/
│       ├── specs/2026-07-14-dfr-trigger-design.md
│       └── plans/2026-07-14-dfr-trigger-implementation.md
├── artifacts/                           # non-sensitive visual verification images
└── tests/
    ├── conftest.py
    ├── test_health.py
    ├── test_config_store.py
    ├── test_security.py
    ├── test_audit_idempotency.py
    ├── test_fh2_dispatch.py
    ├── test_geocoding.py
    └── browser/test_ui.py
```

---

### Task 1: Reproducible App Scaffold And Project-Level Superpowers

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `AGENTS.md`
- Create: `app/__init__.py`
- Create: `app/settings.py`
- Create: `app/main.py`
- Create: `tests/test_health.py`
- Create: `opencode.json`
- Create: `.opencode/package.json`
- Create: `.opencode/plugins/superpowers-guard.js`

**Interfaces:**
- Produces: `app.settings.Settings`, `app.settings.get_settings()`, `app.main.create_app()`, `GET /api/health`
- Produces: project-local Superpowers v6.1.1 loading without global configuration changes

- [ ] **Step 1: Write the failing health test**

```python
# tests/test_health.py
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_health_reports_mock_mode(tmp_path):
    settings = Settings(data_dir=tmp_path, live_dispatch_enabled=False)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "mock"}
```

- [ ] **Step 2: Run the test to verify the scaffold is absent**

Run: `uv run pytest tests/test_health.py -v`

Expected: FAIL because `pyproject.toml` or `app.main` does not exist

- [ ] **Step 3: Add pinned dependencies and runtime settings**

```toml
# pyproject.toml
[project]
name = "dfr-trigger"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "cryptography==45.0.4",
  "fastapi==0.115.14",
  "httpx==0.28.1",
  "jinja2==3.1.6",
  "pydantic-settings==2.10.1",
  "uvicorn[standard]==0.34.3",
]

[dependency-groups]
dev = [
  "playwright==1.53.0",
  "pytest==8.4.1",
  "pytest-asyncio==1.0.0",
  "pytest-playwright==0.7.0",
  "respx==0.22.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

```markdown
<!-- AGENTS.md -->
# DFR Trigger

- Use Superpowers for design, TDD, implementation review, and verification.
- Keep real FH2 dispatch disabled until every release gate passes.
- Use only synthetic data in automated tests.
- Never commit credentials, runtime databases, or customer data.
- Treat the approved spec and implementation plan as the source of truth.
```

```python
# app/settings.py
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    data_dir: Path = Field(default=Path("data"), validation_alias="DFR_DATA_DIR")
    live_dispatch_enabled: bool = False
    fh2_contract_verified: bool = False
    dfr_config_key: str | None = None
    csrf_secret: str = "mock-only-change-before-live"
    trusted_identity_header: str | None = None
    trusted_proxy_cidrs: str = ""
    public_origin: str = "http://testserver"
    fh2_timeout_seconds: float = 10.0
    geocoding_timeout_seconds: float = 5.0
    log_retention_days: int = 7
    dispatches_per_user_per_minute: int = 5
    dispatches_per_instance_per_minute: int = 20
    dispatches_per_project_per_minute: int = 20
    dispatch_concurrency_per_project: int = 1

    @property
    def mode(self) -> Literal["mock", "live"]:
        return "live" if self.live_dispatch_enabled else "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Implement the minimal FastAPI factory**

```python
# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.settings = runtime
        yield

    app = FastAPI(title="DFR Trigger", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": runtime.mode}

    return app


app = create_app()
```

- [ ] **Step 5: Add project-local Superpowers configuration**

```json
// opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "./.opencode/plugins/superpowers-guard.js",
    "superpowers@git+https://github.com/obra/superpowers.git#v6.1.1"
  ],
  "agent": {
    "general": {
      "permission": {
        "todowrite": "allow"
      }
    }
  }
}
```

```javascript
// .opencode/plugins/superpowers-guard.js
export default async function SuperpowersDfrGuard() {
  process.env.SUPERPOWERS_DISABLE_TELEMETRY = "1";
  process.env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1";
  return {};
}
```

```json
// .opencode/package.json
{
  "private": true,
  "dependencies": {
    "@opencode-ai/plugin": "1.17.16"
  }
}
```

- [ ] **Step 6: Add secret and runtime exclusions**

```gitignore
# .gitignore
.env
.opencode/node_modules/
.pytest_cache/
.superpowers/
.venv/
__pycache__/
*.py[cod]
data/
test-results/
playwright-report/
```

```dotenv
# .env.example
LIVE_DISPATCH_ENABLED=false
FH2_CONTRACT_VERIFIED=false
DFR_DATA_DIR="/home/opencode/vibe-coding/DFR Trigger/data"
DFR_CONFIG_KEY=
CSRF_SECRET=
TRUSTED_IDENTITY_HEADER=
TRUSTED_PROXY_CIDRS=
PUBLIC_ORIGIN=
```

- [ ] **Step 7: Install, lock, and verify**

Run: `uv sync --dev && npm install --prefix .opencode && uv run pytest tests/test_health.py -v`

Expected: health test PASS and `uv.lock` created

Run: `opencode agent list`

Expected: command succeeds without `invalid`, `Expected`, or permission schema errors

Run: `SUPERPOWERS_DISABLE_TELEMETRY=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 opencode run "Use the skill tool to load the skill named using-superpowers. If it loads, reply exactly: SUPERPOWERS_SKILL_LOADED. Do not modify files."`

Expected: `SUPERPOWERS_SKILL_LOADED`

- [ ] **Step 8: Commit the scaffold**

```bash
git add .gitignore .env.example pyproject.toml uv.lock app tests/test_health.py opencode.json .opencode
git commit -m "chore: scaffold DFR trigger service"
```

---

### Task 2: SQLite Schema, AES-GCM Configuration, And Creator ID

**Files:**
- Create: `app/db.py`
- Create: `app/schemas.py`
- Create: `app/crypto.py`
- Create: `app/config_store.py`
- Create: `tests/conftest.py`
- Create: `tests/test_config_store.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `Settings.data_dir`, `Settings.dfr_config_key`
- Produces: `Database.connect()`, `Database.initialize()`
- Produces: `ValueCipher.encrypt(str) -> str`, `ValueCipher.decrypt(str) -> str`
- Produces: `ConfigStore.save(ConfigWrite, actor)`, `ConfigStore.load() -> StoredFH2Config | None`, `ConfigStore.status() -> ConfigStatus`
- Produces: `StoredFH2Config(region, user_token, project_uuid, workflow_uuid, creator_id)`

- [ ] **Step 1: Write failing encryption and configuration tests**

```python
# tests/test_config_store.py
import base64
import os

import pytest

from app.config_store import ConfigStore
from app.crypto import ValueCipher
from app.db import Database
from app.schemas import ConfigWrite


def key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_configuration_round_trip_masks_identifiers(tmp_path):
    database = Database(tmp_path / "dfr.db")
    database.initialize()
    store = ConfigStore(database, ValueCipher(key()))
    saved = store.save(
        ConfigWrite(
            region="eu",
            user_token="token-secret",
            project_uuid="bfff3bbe-ecc4-44f4-ae94-9057b69a6a9a",
            workflow_uuid="ccfcb747-87dd-4caa-94e2-c08b5e164dd3",
            creator_id="1988423428261173248",
        ),
        actor="irving.zhang",
    )
    assert saved.token_configured is True
    assert saved.project_uuid_suffix == "69a6a9"
    assert saved.workflow_uuid_suffix == "164dd3"
    assert saved.creator_id_suffix == "173248"
    assert store.load().user_token == "token-secret"


def test_wrong_key_fails_closed(tmp_path):
    database = Database(tmp_path / "dfr.db")
    database.initialize()
    ConfigStore(database, ValueCipher(key())).save(
        ConfigWrite(
            region="global",
            user_token="secret",
            project_uuid="project-123456",
            workflow_uuid="workflow-123456",
            creator_id="creator-123456",
        ),
        actor="tester",
    )
    with pytest.raises(ValueError, match="configuration decryption failed"):
        ConfigStore(database, ValueCipher(key())).load()
```

Add the shared database fixture used by later storage tests:

```python
# tests/conftest.py
import pytest

from app.db import Database


@pytest.fixture
def database(tmp_path):
    value = Database(tmp_path / "dfr.db")
    value.initialize()
    return value
```

- [ ] **Step 2: Run the tests to verify missing storage classes**

Run: `uv run pytest tests/test_config_store.py -v`

Expected: FAIL importing `app.config_store`

- [ ] **Step 3: Implement the SQLite schema and connection factory**

```python
# app/db.py
import sqlite3
from contextlib import closing
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS fh2_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  region TEXT NOT NULL CHECK (region IN ('global', 'eu')),
  user_token TEXT NOT NULL,
  project_uuid TEXT NOT NULL,
  workflow_uuid TEXT NOT NULL,
  creator_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispatch_audit (
  audit_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  actor TEXT NOT NULL,
  priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
  incident_type TEXT,
  location TEXT,
  operator_name TEXT,
  submitted_at TEXT NOT NULL,
  completed_at TEXT,
  duration_ms INTEGER,
  region TEXT NOT NULL,
  request_json TEXT NOT NULL,
  http_status INTEGER,
  response_json TEXT,
  outcome TEXT NOT NULL CHECK (outcome IN ('pending','success','failure','indeterminate')),
  error_category TEXT
);
CREATE TABLE IF NOT EXISTS idempotency (
  idempotency_key TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  reservation_generation TEXT NOT NULL,
  audit_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('processing','completed')),
  result_json TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_submitted_at ON dispatch_audit(submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires_at ON idempotency(expires_at);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.executescript(SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            try:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(idempotency)")
                }
                if "reservation_generation" not in columns:
                    connection.execute(
                        "ALTER TABLE idempotency ADD COLUMN reservation_generation TEXT"
                    )
                connection.execute(
                    """UPDATE idempotency
                       SET reservation_generation=lower(hex(randomblob(16)))
                       WHERE reservation_generation IS NULL"""
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
```

- [ ] **Step 4: Implement exact schemas and AES-256-GCM encryption**

```python
# app/schemas.py
from typing import Literal

from pydantic import BaseModel, Field


Region = Literal["global", "eu"]


class ConfigWrite(BaseModel):
    region: Region
    user_token: str = Field(min_length=8, max_length=4096)
    project_uuid: str = Field(min_length=6, max_length=128)
    workflow_uuid: str = Field(min_length=6, max_length=128)
    creator_id: str = Field(min_length=1, max_length=128)


class StoredFH2Config(ConfigWrite):
    pass


class ConfigStatus(BaseModel):
    region: Region | None = None
    token_configured: bool = False
    project_uuid_suffix: str | None = None
    workflow_uuid_suffix: str | None = None
    creator_id_suffix: str | None = None
```

```python
# app/crypto.py
import base64

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ValueCipher:
    def __init__(self, encoded_key: str):
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except Exception as exc:
            raise ValueError("DFR_CONFIG_KEY must be URL-safe base64") from exc
        if len(key) != 32:
            raise ValueError("DFR_CONFIG_KEY must decode to 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str) -> str:
        nonce = __import__("os").urandom(12)
        ciphertext = self._cipher.encrypt(nonce, value.encode(), b"dfr-trigger-config-v1")
        return base64.urlsafe_b64encode(nonce + ciphertext).decode()

    def decrypt(self, value: str) -> str:
        raw = base64.urlsafe_b64decode(value.encode())
        try:
            return self._cipher.decrypt(raw[:12], raw[12:], b"dfr-trigger-config-v1").decode()
        except (InvalidTag, ValueError) as exc:
            raise ValueError("configuration decryption failed") from exc
```

- [ ] **Step 5: Implement encrypted configuration persistence**

```python
# app/config_store.py
from datetime import datetime, timezone

from app.crypto import ValueCipher
from app.db import Database
from app.schemas import ConfigStatus, ConfigWrite, StoredFH2Config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def suffix(value: str) -> str:
    return value[-6:]


class ConfigStore:
    def __init__(self, database: Database, cipher: ValueCipher):
        self.database = database
        self.cipher = cipher

    def save(self, value: ConfigWrite, actor: str) -> ConfigStatus:
        now = utc_now()
        encrypted = [
            self.cipher.encrypt(value.user_token),
            self.cipher.encrypt(value.project_uuid),
            self.cipher.encrypt(value.workflow_uuid),
            self.cipher.encrypt(value.creator_id),
        ]
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO fh2_config VALUES (1,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET region=excluded.region,
                user_token=excluded.user_token, project_uuid=excluded.project_uuid,
                workflow_uuid=excluded.workflow_uuid, creator_id=excluded.creator_id,
                updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
                (value.region, *encrypted, now, now, actor),
            )
            connection.commit()
        return self.status()

    def load(self) -> StoredFH2Config | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM fh2_config WHERE id=1").fetchone()
        if row is None:
            return None
        return StoredFH2Config(
            region=row["region"],
            user_token=self.cipher.decrypt(row["user_token"]),
            project_uuid=self.cipher.decrypt(row["project_uuid"]),
            workflow_uuid=self.cipher.decrypt(row["workflow_uuid"]),
            creator_id=self.cipher.decrypt(row["creator_id"]),
        )

    def status(self) -> ConfigStatus:
        value = self.load()
        if value is None:
            return ConfigStatus()
        return ConfigStatus(
            region=value.region,
            token_configured=True,
            project_uuid_suffix=suffix(value.project_uuid),
            workflow_uuid_suffix=suffix(value.workflow_uuid),
            creator_id_suffix=suffix(value.creator_id),
        )
```

- [ ] **Step 6: Initialize the database at application startup and fail closed in live mode**

Update `create_app()` lifespan to create `Database(runtime.data_dir / "dfr_trigger.db")`, call `initialize()`, and store it on `app.state.database`. When `dfr_config_key` is present, also store `ConfigStore(database, ValueCipher(runtime.dfr_config_key))` on `app.state.config_store`; otherwise set `app.state.config_store = None`. If `runtime.live_dispatch_enabled` is true and `dfr_config_key` is empty, raise `RuntimeError("DFR_CONFIG_KEY is required in live mode")` before accepting traffic. Configuration routes return `503` when the store is unavailable.

- [ ] **Step 7: Run configuration tests**

Run: `uv run pytest tests/test_config_store.py tests/test_health.py -v`

Expected: all tests PASS; searching the SQLite file for `token-secret` returns no match

- [ ] **Step 8: Commit encrypted configuration storage**

```bash
git add app tests pyproject.toml uv.lock
git commit -m "feat: add encrypted FH2 configuration"
```

---

### Task 3: Trusted Identity, CSRF, Origin Checks, And Rate Limits

**Files:**
- Create: `app/security.py`
- Create: `tests/test_security.py`
- Modify: `app/main.py`
- Modify: `app/settings.py`

**Interfaces:**
- Consumes: `Settings.csrf_secret`, `Settings.public_origin`, `Settings.trusted_identity_header`, `Settings.trusted_proxy_cidrs`
- Produces: `issue_csrf_token()`, `require_state_change(request)`, `trusted_actor(request) -> str`
- Produces: `SlidingWindowLimiter.check(scope, key, limit, window_seconds)`

- [ ] **Step 1: Write failing CSRF, identity, and limiter tests**

```python
# tests/test_security.py
from app.security import SlidingWindowLimiter, create_csrf_token, verify_csrf_token


def test_signed_csrf_token_detects_tampering():
    token = create_csrf_token("secret", now=1_700_000_000)
    assert verify_csrf_token(token, "secret", now=1_700_000_100)
    assert not verify_csrf_token(token + "x", "secret", now=1_700_000_100)


def test_rate_limiter_rejects_sixth_request():
    limiter = SlidingWindowLimiter(clock=lambda: 100.0)
    for _ in range(5):
        limiter.check("dispatch-user", "irving", 5, 60)
    try:
        limiter.check("dispatch-user", "irving", 5, 60)
        assert False, "sixth request should be rejected"
    except RuntimeError as exc:
        assert str(exc) == "rate limit exceeded"
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest tests/test_security.py -v`

Expected: FAIL importing `app.security`

- [ ] **Step 3: Implement signed double-submit CSRF and same-origin validation**

```python
# app/security.py
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def create_csrf_token(secret: str, now: int | None = None) -> str:
    issued = now or int(time.time())
    nonce = secrets.token_urlsafe(24)
    body = f"{issued}.{nonce}"
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_csrf_token(token: str, secret: str, now: int | None = None) -> bool:
    try:
        issued_text, nonce, signature = token.split(".", 2)
        issued = int(issued_text)
    except ValueError:
        return False
    body = f"{issued}.{nonce}"
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    age = (now or int(time.time())) - issued
    return 0 <= age <= 3600 and hmac.compare_digest(signature, expected)


def require_state_change(request: Request) -> None:
    settings = request.app.state.settings
    origin = request.headers.get("origin")
    parsed_origin = urlsplit(origin or "")
    parsed_referer = urlsplit(request.headers.get("referer", ""))
    parsed_public = urlsplit(settings.public_origin)
    if (parsed_origin.scheme, parsed_origin.netloc) != (parsed_public.scheme, parsed_public.netloc):
        raise HTTPException(403, "invalid origin")
    if (parsed_referer.scheme, parsed_referer.netloc) != (parsed_public.scheme, parsed_public.netloc):
        raise HTTPException(403, "invalid referer")
    cookie = request.cookies.get("dfr_csrf")
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or cookie != header:
        raise HTTPException(403, "invalid csrf token")
    if not verify_csrf_token(header, settings.csrf_secret):
        raise HTTPException(403, "expired csrf token")


def trusted_actor(request: Request) -> str:
    settings = request.app.state.settings
    if not settings.live_dispatch_enabled:
        return "mock-user"
    header_name = settings.trusted_identity_header
    if not header_name:
        raise HTTPException(503, "trusted identity is not configured")
    networks = [ipaddress.ip_network(item.strip()) for item in settings.trusted_proxy_cidrs.split(",") if item.strip()]
    client_ip = ipaddress.ip_address(request.client.host)
    if not networks or not any(client_ip in network for network in networks):
        raise HTTPException(403, "untrusted proxy")
    actor = request.headers.get(header_name)
    if not actor or len(actor) > 256:
        raise HTTPException(403, "missing trusted identity")
    return actor


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.events = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, scope: str, key: str, limit: int, window_seconds: int) -> None:
        with self.lock:
            now = self.clock()
            bucket = self.events[(scope, key)]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                raise RuntimeError("rate limit exceeded")
            bucket.append(now)
```

- [ ] **Step 4: Add `/api/bootstrap` and security headers**

In `create_app()`, add middleware that sets `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, and `Cache-Control: no-store` on API responses. Add `/api/bootstrap` that calls `trusted_actor`, returns mode plus configuration status later, and sets `dfr_csrf` with `SameSite=Strict`, `Path=/`, `HttpOnly=false`, one-hour max age, and `Secure=true` exactly when `PUBLIC_ORIGIN` uses HTTPS. Live-mode startup already requires HTTPS; the conditional permits local HTTP browser tests.

- [ ] **Step 5: Run security tests**

Run: `uv run pytest tests/test_security.py tests/test_health.py -v`

Expected: all tests PASS

- [ ] **Step 6: Commit security primitives**

```bash
git add app tests
git commit -m "feat: enforce request security controls"
```

---

### Task 4: Audit Redaction, Fail-Closed Logging, And Idempotency

**Files:**
- Create: `app/redaction.py`
- Create: `app/audit_store.py`
- Create: `app/idempotency.py`
- Create: `app/maintenance.py`
- Create: `tests/test_audit_idempotency.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `Database`
- Produces: `sanitize(value, sensitive_values=())`, `serialize_sanitized(value, sensitive_values=(), max_bytes=65536)`
- Produces: `AuditStore.create_pending(request, actor, idempotency_key, region, sensitive_values) -> str`, `AuditStore.complete(audit_id, result, duration_ms, sensitive_values)`, `AuditStore.list(query, priority, outcome, limit, cursor)`, `AuditStore.cleanup(retention_days)`
- Produces: `IdempotencyStore.reserve(key, incident_id, fingerprint) -> Reservation(state, result, generation)`, `IdempotencyStore.complete(key, generation, result, sensitive_values)`, `IdempotencyStore.cleanup()`

- [ ] **Step 1: Write failing redaction and duplicate-reservation tests**

```python
# tests/test_audit_idempotency.py
import json

from app.idempotency import IdempotencyStore
from app.redaction import serialize_sanitized


def test_recursive_redaction_masks_secrets_and_project_uuid():
    value = {
        "X-User-Token": "secret",
        "nested": {"password": "hidden", "project_uuid": "project-123456"},
        "description": "safe token-secret must disappear",
    }
    result = json.loads(serialize_sanitized(value, sensitive_values=("token-secret",)))
    assert result["X-User-Token"] == "[REDACTED]"
    assert result["nested"]["password"] == "[REDACTED]"
    assert result["nested"]["project_uuid"].endswith("123456")
    assert "project" not in result["nested"]["project_uuid"]
    assert result["description"] == "safe [REDACTED_VALUE] must disappear"


def test_idempotency_same_fingerprint_replays_existing(database):
    store = IdempotencyStore(database, retention_days=7)
    first = store.reserve("key-1", "INC-1", "hash-a")
    second = store.reserve("key-1", "INC-1", "hash-a")
    conflict = store.reserve("key-1", "INC-1", "hash-b")
    assert first.state == "created"
    assert first.generation
    assert second.state == "processing"
    assert second.generation == first.generation
    assert conflict.state == "conflict"
```

- [ ] **Step 2: Run tests to verify the modules are missing**

Run: `uv run pytest tests/test_audit_idempotency.py -v`

Expected: FAIL importing redaction/idempotency modules

- [ ] **Step 3: Implement recursive redaction and bounded serialization**

```python
# app/redaction.py
import json


SECRET_MARKERS = ("token", "secret", "password", "authorization", "cookie", "config_key", "encryption_key")
MASKED_SUFFIX_FIELDS = {"project_uuid", "workflow_uuid", "creator_id", "creator"}


def _mask_suffix(value: object) -> str:
    text = str(value)
    return "*" * max(0, len(text) - 6) + text[-6:]


def sanitize(value: object, sensitive_values: tuple[str, ...] = ()) -> object:
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            lowered = str(key).lower().replace("-", "_")
            if any(marker in lowered for marker in SECRET_MARKERS):
                cleaned[key] = "[REDACTED]"
            elif lowered in MASKED_SUFFIX_FIELDS:
                cleaned[key] = _mask_suffix(child)
            else:
                cleaned[key] = sanitize(child, sensitive_values)
        return cleaned
    if isinstance(value, list):
        return [sanitize(item, sensitive_values) for item in value]
    if isinstance(value, str):
        cleaned = value
        for sensitive in sensitive_values:
            if len(sensitive) >= 6:
                cleaned = cleaned.replace(sensitive, "[REDACTED_VALUE]")
        return cleaned
    return value


def serialize_sanitized(
    value: object,
    sensitive_values: tuple[str, ...] = (),
    max_bytes: int = 65_536,
) -> str:
    encoded = json.dumps(
        sanitize(value, sensitive_values), ensure_ascii=True, separators=(",", ":")
    ).encode()
    if len(encoded) <= max_bytes:
        return encoded.decode()
    preview = encoded[: max_bytes // 3].decode("ascii", "replace")
    return json.dumps(
        {"truncated": True, "original_bytes": len(encoded), "preview": preview},
        ensure_ascii=True,
        separators=(",", ":"),
    )
```

- [ ] **Step 4: Implement transactional idempotency**

Create a frozen `Reservation(state: Literal['created','processing','completed','conflict'], result: dict | None, generation: str | None)` dataclass. `reserve()` must use `BEGIN IMMEDIATE`, create and return a cryptographically random generation for each new reservation, insert with a seven-day expiry, and compare the stored fingerprint for existing rows. Expired replacement must delete the audit row tied to that expired idempotency key in the same transaction before inserting the new generation. `complete(key, generation, result, sensitive_values)` updates only the matching `processing` generation and raises `RuntimeError("stale idempotency reservation")` otherwise. Completion stores recursively redacted valid JSON within 64 KiB; oversized results preserve the top-level `incident_id`, `audit_id`, `outcome`, `http_status`, `error_category`, and `replayed` envelope when present while replacing only oversized non-envelope details such as `body`. A completed matching key returns the stored replay-compatible result; a mismatched fingerprint returns conflict.

- [ ] **Step 5: Implement pending-first audit operations**

`AuditStore.create_pending()` inserts a complete sanitized request record plus priority, incident type, location, and operator before any FH2 call. `complete()` updates status, response, duration, and category in one transaction. Both methods receive the decrypted token, Project UUID, Workflow UUID, and Creator ID as `sensitive_values` and redact any occurrence even when FH2 embeds one inside a string. `list()` searches Incident ID, incident type, location, and operator; supports priority, outcome, limit `1..100`, and cursor pagination. `cleanup()` deletes audit rows older than seven days and expired idempotency rows.

- [ ] **Step 6: Add tests for audit failure and seven-day cleanup**

Use a temporary SQLite database, insert one eight-day-old and one current row, call cleanup, and assert only the current row remains. Assert `len(serialize_sanitized(oversized_value).encode()) <= 65_536` and that the result remains valid JSON. Close or make the database unwritable before `create_pending()` and assert the exception is propagated; no dispatch test may catch and ignore it.

- [ ] **Step 7: Schedule cleanup on startup and every 24 hours**

```python
# app/maintenance.py
import asyncio


async def cleanup_loop(audit_store, idempotency_store, retention_days: int) -> None:
    while True:
        audit_store.cleanup(retention_days)
        idempotency_store.cleanup()
        await asyncio.sleep(86_400)
```

In the FastAPI lifespan, construct both stores, run one cleanup before serving traffic, create `asyncio.create_task(cleanup_loop(audit_store, idempotency_store, runtime.log_retention_days))`, and on shutdown cancel and await the task under `contextlib.suppress(asyncio.CancelledError)`. Add a test with monkeypatched cleanup methods that starts and closes `TestClient` and asserts both methods were called at least once.

- [ ] **Step 8: Run storage tests**

Run: `uv run pytest tests/test_audit_idempotency.py tests/test_config_store.py -v`

Expected: all tests PASS

- [ ] **Step 9: Commit audit and idempotency**

```bash
git add app tests
git commit -m "feat: add dispatch audit and idempotency"
```

---

### Task 5: FH2 Contract Evidence, Adapter, And Dispatch Orchestration

**Files:**
- Create: `docs/fh2-contract-evidence.md`
- Create: `app/fh2.py`
- Create: `app/dispatch.py`
- Create: `app/api.py`
- Create: `tests/test_fh2_dispatch.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ConfigStore`, `AuditStore`, `IdempotencyStore`, `SlidingWindowLimiter`
- Produces: `DispatchRequest`, `DispatchResult`, `build_fh2_payload(request, config) -> dict`
- Produces: `FH2Client.send(config, payload) -> FH2Response`
- Produces: `DispatchService.submit(request, actor, idempotency_key) -> DispatchResult`
- Produces: `POST /api/dispatch`, `GET/PUT /api/config`, `POST /api/config/test`, `GET /api/logs`

- [ ] **Step 1: Record the verified contract boundary**

Write `docs/fh2-contract-evidence.md` with these confirmed facts and source date:

```markdown
# FH2 Triggered Workflow Contract Evidence

- Verified: 2026-07-14
- Official manual: https://fh.dji.com/user-manual/en/automation/triggered-workflow.html
- Method: POST
- Global base: https://es-flight-api-us.djigate.com
- Europe base: https://es-flight-api-eu.djigate.com
- Headers: Content-Type: application/json, X-User-Token, x-project-uuid
- Body: workflow_uuid, trigger_type=0, name, params.creator, params.latitude,
  params.longitude, params.level (1-5), params.desc
- Coordinates: WGS84
- Success: HTTP 200 means accepted and processing started; it does not mean mission completion
- Documented errors: 400, 401, 403, 500; business code 245008 means workflow/project mismatch
- Public-cloud path: not exposed by the current static manual; existing tested trigger uses
  /openapi/v0.1/workflow. Keep live mode disabled until a current authorized request or
  DJI API reference confirms the full URL.
```

- [ ] **Step 2: Write failing payload and no-retry tests**

```python
# tests/test_fh2_dispatch.py
import httpx
import pytest

from app.fh2 import FH2Client, build_fh2_payload
from app.schemas import DispatchRequest, StoredFH2Config


def request() -> DispatchRequest:
    return DispatchRequest(
        incident_id="INC-20260714-0001",
        latitude=48.8566,
        longitude=2.3522,
        priority=5,
        incident_type="Fire",
        description="Synthetic integration test",
    )


def config() -> StoredFH2Config:
    return StoredFH2Config(
        region="eu",
        user_token="secret-token",
        project_uuid="project-uuid",
        workflow_uuid="workflow-uuid",
        creator_id="creator-123",
    )


def test_payload_uses_official_fields_and_creator():
    payload = build_fh2_payload(request(), config())
    assert payload["workflow_uuid"] == "workflow-uuid"
    assert payload["trigger_type"] == 0
    assert payload["params"]["creator"] == "creator-123"
    assert payload["params"]["level"] == 5
    assert "Incident Type: Fire" in payload["params"]["desc"]


@pytest.mark.asyncio
async def test_timeout_is_indeterminate_and_not_retried(respx_mock):
    route = respx_mock.post("https://es-flight-api-eu.djigate.com/openapi/v0.1/workflow").mock(
        side_effect=httpx.ReadTimeout("timeout")
    )
    result = await FH2Client(timeout_seconds=0.1).send(config(), build_fh2_payload(request(), config()))
    assert result.outcome == "indeterminate"
    assert route.call_count == 1
```

- [ ] **Step 3: Add strict dispatch schemas**

```python
# append to app/schemas.py
from pydantic import model_validator


IncidentType = Literal[
    "Security Alarm", "Fire", "Traffic Accident", "Crime in Progress",
    "Search & Rescue", "Missing Person", "Other"
]


class DispatchRequest(BaseModel):
    model_config = {"extra": "forbid"}
    incident_id: str = Field(pattern=r"^INC-[A-Z0-9-]{6,40}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    priority: int = Field(default=5, ge=1, le=5)
    incident_type: IncidentType | None = None
    custom_incident_type: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=300)
    operator_name: str | None = Field(default=None, max_length=120)
    caller_phone: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_other(self):
        if self.incident_type == "Other" and not self.custom_incident_type:
            raise ValueError("custom_incident_type is required for Other")
        if self.incident_type != "Other" and self.custom_incident_type:
            raise ValueError("custom_incident_type requires Other")
        return self


class FH2Response(BaseModel):
    outcome: Literal["success", "failure", "indeterminate"]
    http_status: int | None = None
    body: object | None = None
    error_category: str | None = None


class DispatchResult(FH2Response):
    incident_id: str
    audit_id: str
    replayed: bool = False
```

- [ ] **Step 4: Implement the fixed-host FH2 adapter**

`app/fh2.py` must define only these hosts:

```python
FH2_BASE_URLS = {
    "global": "https://es-flight-api-us.djigate.com",
    "eu": "https://es-flight-api-eu.djigate.com",
}
WORKFLOW_PATH = "/openapi/v0.1/workflow"
```

Use one `httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), follow_redirects=False)`, exact headers, and one POST call. Parse JSON when possible and otherwise store bounded text. Map `200` to success, other HTTP responses to failure, `ReadTimeout`/`WriteTimeout` to indeterminate, and connection failure before write to failure. Do not configure retries.

- [ ] **Step 5: Implement stable payload construction**

Build `desc` in this exact order, omitting empty values: Incident Type, Location, Operator, Caller, Description, Incident ID. Use the custom type when Incident Type is Other. Build the request name as `Emergency Alert - [{incident_id}]` and include only documented FH2 fields.

- [ ] **Step 6: Implement dispatch orchestration**

`DispatchService.submit()` must:

1. Load a complete encrypted configuration or return configuration error.
2. Enforce user, instance, and project rate limits plus a per-project concurrency semaphore.
3. Hash canonical request JSON with SHA-256.
4. Reserve the idempotency key and retain `reservation.generation` as the ownership token for a newly created reservation.
5. Return an existing completed result with `replayed=True` when replayed.
   A matching key still processing returns HTTP `409` with `request processing`; a mismatched fingerprint returns HTTP `409` with `idempotency conflict`.
6. Build `sensitive_values=(user_token, project_uuid, workflow_uuid, creator_id)` and create the pending audit row before selecting a live or mock client.
7. Use a deterministic mock success response when live mode is off.
8. Refuse live mode unless `fh2_contract_verified` is true.
9. Call FH2 once, complete audit with the same `sensitive_values`, then call `idempotency_store.complete(idempotency_key, reservation.generation, result, sensitive_values)` and return `DispatchResult`.
10. Mark timeout as indeterminate and never retry.

If idempotency completion raises exactly `RuntimeError("stale idempotency reservation")`, fail closed and map it to HTTP `409` with `stale idempotency reservation`. Do not retry FH2 and do not read, complete, or overwrite the replacement generation. Propagate any other unexpected `RuntimeError`.

- [ ] **Step 7: Add protected API routes**

Register `/api/config`, `/api/config/test`, `/api/dispatch`, and `/api/logs` in `app/api.py`. All state-changing routes call `require_state_change()` and `trusted_actor()`. `POST /api/dispatch` requires `Idempotency-Key` matching `[A-Za-z0-9_-]{16,128}`. `GET /api/config` returns only `ConfigStatus`. `POST /api/config/test` validates stored completeness and returns `{"valid": true, "fh2_request_sent": false}` until a documented non-dispatching validation endpoint exists.

- [ ] **Step 8: Run adapter and dispatch tests**

Run: `uv run pytest tests/test_fh2_dispatch.py tests/test_security.py tests/test_audit_idempotency.py -v`

Expected: all tests PASS, timeout route call count is exactly one, and test output contains no token

- [ ] **Step 9: Commit the backend trigger flow**

```bash
git add app tests docs/fh2-contract-evidence.md
git commit -m "feat: implement guarded FH2 dispatch"
```

---

### Task 6: Fixed-Host Address Geocoding

**Files:**
- Create: `app/geocoding.py`
- Create: `tests/test_geocoding.py`
- Modify: `app/api.py`
- Modify: `app/schemas.py`

**Interfaces:**
- Produces: `Geocoder.search(query) -> GeocodeResult | None`
- Produces: `POST /api/geocode`

- [ ] **Step 1: Write failing geocoding tests**

```python
# tests/test_geocoding.py
import pytest

from app.geocoding import Geocoder


@pytest.mark.asyncio
async def test_geocoder_uses_fixed_nominatim_host(respx_mock):
    route = respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=__import__("httpx").Response(
            200,
            json=[{"lat": "48.8566", "lon": "2.3522", "display_name": "Paris, France"}],
        )
    )
    result = await Geocoder(timeout_seconds=1).search("Paris")
    assert route.called
    assert result.latitude == 48.8566
    assert result.longitude == 2.3522


@pytest.mark.asyncio
async def test_geocoder_rejects_blank_query():
    with pytest.raises(ValueError, match="query is required"):
        await Geocoder(timeout_seconds=1).search("   ")
```

- [ ] **Step 2: Run tests to verify missing adapter**

Run: `uv run pytest tests/test_geocoding.py -v`

Expected: FAIL importing `app.geocoding`

- [ ] **Step 3: Implement the allowlisted adapter and cache**

Use only `https://nominatim.openstreetmap.org/search`, `follow_redirects=False`, `format=jsonv2`, `limit=1`, an explicit `User-Agent: DFR-Trigger/0.1`, a five-second timeout, a five-minute in-memory cache, and a process-wide minimum interval of one second between uncached requests. Parse numeric latitude/longitude and return display name. Do not expose a URL parameter in any interface.

- [ ] **Step 4: Add the protected route**

Add `GeocodeRequest(query: str = Field(min_length=1, max_length=200))` and `GeocodeResult(latitude, longitude, display_name)`. `POST /api/geocode` requires CSRF and trusted identity because it proxies user input, then returns `404` when no result exists and `503` on provider failure.

- [ ] **Step 5: Run geocoding and full backend tests**

Run: `uv run pytest tests -v --ignore=tests/browser`

Expected: all backend tests PASS

- [ ] **Step 6: Commit geocoding**

```bash
git add app tests/test_geocoding.py
git commit -m "feat: add bounded address geocoding"
```

---

### Task 7: FH2-Inspired Shell, Navigation Animation, Icons, And Map

**Files:**
- Create: `app/templates/index.html`
- Create: `app/static/styles.css`
- Create: `app/static/js/api.js`
- Create: `app/static/js/navigation.js`
- Create: `app/static/js/map.js`
- Create: `app/static/js/main.js`
- Create: `tests/browser/test_ui.py`
- Modify: `tests/conftest.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `GET /api/bootstrap`
- Produces: `NavigationController`, `MapController`, `ApiClient`
- Produces: root page with `data-nav-expanded=false`, one `.functional-panel`, and map coordinate events

- [ ] **Step 1: Write failing browser tests for shell geometry**

Extend `tests/conftest.py` with a real local Uvicorn fixture. It preloads synthetic encrypted configuration so Dispatch is enabled without exposing or calling FH2:

```python
import base64
import os
import socket
import threading
import time

import uvicorn

from app.config_store import ConfigStore
from app.crypto import ValueCipher
from app.db import Database
from app.main import create_app
from app.schemas import ConfigWrite
from app.settings import Settings


@pytest.fixture
def live_server_url(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    encoded_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings = Settings(
        data_dir=tmp_path,
        live_dispatch_enabled=False,
        dfr_config_key=encoded_key,
        csrf_secret="browser-test-secret",
        public_origin=url,
    )
    database = Database(tmp_path / "dfr_trigger.db")
    database.initialize()
    ConfigStore(database, ValueCipher(encoded_key)).save(
        ConfigWrite(
            region="eu",
            user_token="synthetic-test-token",
            project_uuid="project-123456",
            workflow_uuid="workflow-123456",
            creator_id="creator-123456",
        ),
        actor="browser-test",
    )
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield url
    server.should_exit = True
    thread.join(timeout=5)
```

```python
# tests/browser/test_ui.py
from playwright.sync_api import Page, expect


def test_navigation_expands_and_moves_panel(page: Page, live_server_url: str):
    page.goto(live_server_url)
    rail = page.locator("#nav-rail")
    panel = page.locator("#functional-panel")
    expect(rail).to_have_css("width", "49px")
    collapsed_left = panel.bounding_box()["x"]
    page.get_by_role("button", name="Expand navigation").click()
    expect(rail).to_have_css("width", "131px")
    expect(page.get_by_text("Configuration", exact=True)).to_be_visible()
    assert panel.bounding_box()["x"] == collapsed_left + 82


def test_map_click_populates_coordinates(page: Page, live_server_url: str):
    page.goto(live_server_url)
    page.locator("#map").click(position={"x": 400, "y": 300})
    expect(page.locator("#latitude")).not_to_have_value("")
    expect(page.locator("#longitude")).not_to_have_value("")
```

- [ ] **Step 2: Run the fixture-backed browser tests and verify failure**

Run: `uv run pytest tests/browser/test_ui.py -v`

Expected: FAIL because root UI and controls do not exist

- [ ] **Step 3: Serve the Jinja2 template and static assets**

Mount `/static` with `StaticFiles`, create `Jinja2Templates(directory="app/templates")`, and return `index.html` from `/`. The HTML must load Leaflet 1.9.4 CSS/JS and Lucide 0.544.0 from pinned URLs, with exact versions and `crossorigin="anonymous"`. CSP permits only same-origin scripts/styles plus these pinned asset hosts and `https://tile.openstreetmap.org` images.

- [ ] **Step 4: Build the semantic shell**

`index.html` contains:

```html
<aside id="nav-rail" aria-label="Primary navigation">
  <button id="nav-toggle" aria-label="Expand navigation" aria-expanded="false">
    <i data-lucide="menu"></i>
  </button>
  <button class="nav-item is-active" data-module="dispatch">
    <i data-lucide="drone"></i><span>Dispatch</span>
  </button>
  <button class="nav-item" data-module="configuration">
    <i data-lucide="wrench"></i><span>Configuration</span>
  </button>
  <button class="nav-item" data-module="logs">
    <i data-lucide="book-open"></i><span>Log</span>
  </button>
</aside>
<section id="functional-panel" aria-live="polite"></section>
<main id="map" aria-label="Incident map"></main>
```

- [ ] **Step 5: Implement exact layout and animation tokens**

```css
:root {
  --rail-collapsed: 49px;
  --rail-expanded: 131px;
  --panel-width: 250px;
  --motion: 220ms cubic-bezier(0.4, 0, 0.2, 1);
  --panel-fade: 150ms ease;
  --fh2-bg: #202020;
  --fh2-panel: #242424;
  --fh2-border: #3a3a3a;
  --fh2-blue: #2f73d9;
  --fh2-text: #f2f3f5;
  --fh2-muted: #a4a8ae;
}
#nav-rail { width: var(--rail-collapsed); transition: width var(--motion); }
body[data-nav-expanded="true"] #nav-rail { width: var(--rail-expanded); }
#functional-panel {
  left: var(--rail-collapsed); width: var(--panel-width);
  transition: left var(--motion), opacity var(--panel-fade);
}
body[data-nav-expanded="true"] #functional-panel { left: var(--rail-expanded); }
#map {
  left: calc(var(--rail-collapsed) + var(--panel-width));
  transition: left var(--motion);
}
body[data-nav-expanded="true"] #map { left: calc(var(--rail-expanded) + var(--panel-width)); }
.nav-item svg { width: 24px; height: 24px; stroke-width: 2; flex: none; }
```

- [ ] **Step 6: Implement navigation and map controllers**

`NavigationController` toggles `body.dataset.navExpanded`, updates `aria-expanded` and label, calls `map.invalidateSize({animate: false})` after `220ms`, and swaps one panel template with a `150ms` opacity fade. `MapController` initializes Leaflet with OSM attribution, keeps one marker, rounds map-click coordinates to six decimals, writes `#latitude/#longitude`, dispatches a `dfr:coordinates` event, and exposes `setCoordinates(lat, lon)`.

Use the fixed tile template `https://tile.openstreetmap.org/{z}/{x}/{y}.png` so CSP needs only that one OSM image host.

- [ ] **Step 7: Install Playwright browser and run UI tests**

Run: `uv run playwright install chromium`

Run: `uv run pytest tests/browser/test_ui.py -v`

Expected: shell geometry and map tests PASS

- [ ] **Step 8: Commit the UI shell**

```bash
git add app tests/browser
git commit -m "feat: add FH2-style navigation and map"
```

---

### Task 8: Dispatch, Configuration, And Log Panel Interactions

**Files:**
- Create: `app/static/js/dispatch.js`
- Create: `app/static/js/configuration.js`
- Create: `app/static/js/logs.js`
- Modify: `app/templates/index.html`
- Modify: `app/static/js/api.js`
- Modify: `app/static/js/main.js`
- Modify: `app/static/styles.css`
- Modify: `tests/browser/test_ui.py`

**Interfaces:**
- Consumes: `/api/bootstrap`, `/api/dispatch`, `/api/config`, `/api/config/test`, `/api/logs`, `/api/geocode`
- Produces: complete three-panel user workflow with priority 5 and one-click submission

- [ ] **Step 1: Add failing browser tests for confirmed fields and behavior**

```python
def test_dispatch_defaults_and_optional_fields(page: Page, live_server_url: str):
    page.goto(live_server_url)
    expect(page.locator("#priority")).to_have_value("5")
    expect(page.locator("#incident-type")).to_be_visible()
    expect(page.locator("#description")).to_be_visible()
    page.locator("#incident-type").select_option("Other")
    expect(page.locator("#custom-incident-type")).to_be_visible()


def test_configuration_never_renders_saved_token(page: Page, live_server_url: str):
    page.goto(live_server_url)
    page.get_by_role("button", name="Configuration").click()
    expect(page.locator("#token-status")).to_contain_text("Configured")
    expect(page.locator("#user-token")).to_have_value("")


def test_single_click_locks_dispatch_button(page: Page, live_server_url: str):
    page.goto(live_server_url)
    page.locator("#latitude").fill("48.8566")
    page.locator("#longitude").fill("2.3522")
    page.get_by_role("button", name="Dispatch").click()
    expect(page.get_by_role("button", name="Dispatching")).to_be_disabled()
```

- [ ] **Step 2: Run browser tests and verify failure**

Run: `uv run pytest tests/browser/test_ui.py -v`

Expected: new tests FAIL because panels are incomplete

- [ ] **Step 3: Implement the same-origin API client**

`ApiClient.bootstrap()` calls `/api/bootstrap`, reads the `dfr_csrf` cookie, and stores no credentials. `request()` sends `Content-Type: application/json`, `X-CSRF-Token` for non-GET methods, and never retries. It parses JSON error details into a typed `ApiError` without placing request bodies in console logs.

- [ ] **Step 4: Implement Dispatch panel fields**

Render latitude, longitude, Location, Incident Type, custom Other input, Priority `1..5`, Operator Name, Caller Phone, and Description. Mark only coordinates and priority required. Use `crypto.randomUUID()` to create `Idempotency-Key`; generate Incident ID as `INC-${UTC compact timestamp}-${four random uppercase hex}`. Disable the button while in flight. On timeout, show `Outcome unknown; check Log before trying again` and do not auto-resubmit.

- [ ] **Step 5: Implement Configuration panel safely**

Render Global/Europe, blank token, Project UUID, Workflow UUID, and Creator ID. Set Creator ID placeholder to `1988423428261173248` but leave its value empty. Show only configured status and six-character suffixes from `ConfigStatus`. Save sends complete replacement values. Test Configuration calls `/api/config/test` and renders `Configuration format validated. No FH2 task was created.`

- [ ] **Step 6: Implement Log panel**

Render search, priority filter, outcome filter, refresh button, and records newest first. Each record shows Incident ID, timestamp, actor, priority, status, duration, and expandable sanitized request/response JSON. Use `textContent`, never `innerHTML`, for server-returned values. Default limit is 50 and maximum 100.

- [ ] **Step 7: Add responsive and accessibility behavior**

At widths below `768px`, keep the 49px icon rail, make the 250px panel an overlay that can close, and preserve manual coordinate entry. Add visible focus rings, `aria-live` status announcements, labels for every field, Escape-to-close on mobile, and reduced-motion handling that sets animation durations to `0ms`.

- [ ] **Step 8: Run browser and backend tests**

Run: `uv run pytest tests -v`

Expected: all tests PASS; browser checks confirm priority 5, optional fields, editable Creator ID, masked configuration, and disabled in-flight button

- [ ] **Step 9: Commit complete panel interactions**

```bash
git add app tests/browser
git commit -m "feat: complete DFR trigger workflows"
```

---

### Task 9: Deployment, Release Gates, Visual Evidence, And Authorized Smoke Test

**Files:**
- Create: `publish.yml`
- Create: `tests/test_release_gates.py`
- Create: `docs/release-checklist.md`
- Modify: `.env.example`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: all application modules and DreamCoder publish tooling
- Produces: Mock-only DreamCoder URL first; live mode only after recorded gate evidence
- Produces: collapsed, expanded, and mid-animation screenshots

- [ ] **Step 1: Write failing startup gate tests**

```python
# tests/test_release_gates.py
import pytest

from app.main import create_app
from app.settings import Settings


def test_live_mode_requires_contract_key_identity_and_proxy(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        live_dispatch_enabled=True,
        fh2_contract_verified=False,
        dfr_config_key=None,
        trusted_identity_header=None,
        trusted_proxy_cidrs="",
    )
    with pytest.raises(RuntimeError, match="live mode release gates failed"):
        create_app(settings)
```

- [ ] **Step 2: Implement one aggregated live-mode startup validator**

Before creating routes, collect missing live requirements: contract verification, 32-byte AES key, non-default CSRF secret, HTTPS public origin, trusted identity header, and trusted proxy CIDRs. Raise one `RuntimeError` listing missing names. Mock mode must start without production secrets and display a visible `MOCK MODE` badge.

- [ ] **Step 3: Add DreamCoder backend declaration**

```yaml
# publish.yml
app_name: dfr-trigger
type: backend

dependencies:
  - python@3.12
  - uv

backend:
  path: .
  build: uv sync --frozen --no-dev
  start: uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8080 --no-proxy-headers
  port: 8080
  health_check: http://127.0.0.1:8080/api/health
  health_timeout: 60
```

DreamCoder deployment must use `visibility=instance_members`. Do not publish if `API_BASE_URL`, `INSTANCE_ID`, or `INSTANCE_TOKEN` is absent; do not guess missing platform values.

- [ ] **Step 4: Create the release checklist with evidence slots that are completed during execution**

The checklist must require command output or screenshots for:

- UI and every API route reject non-members at the DreamCoder edge.
- Direct backend-origin access is unavailable.
- The configured identity header cannot be spoofed from the public edge.
- `/home/opencode/vibe-coding/DFR Trigger/data` persists after service restart.
- Deployment secrets are absent from Git, logs, HTML, and API responses.
- Full FH2 URL/path is confirmed by an authorized current request or API reference.
- The actual FH2 test project, Project UUID, Workflow UUID, and Creator ID belong together.
- Test credential is revocable and scoped to the test project.

If any item lacks evidence, mark release mode `Mock` and do not set `LIVE_DISPATCH_ENABLED=true`.

- [ ] **Step 5: Run all automated verification**

Run: `uv run pytest tests -v`

Expected: all tests PASS

Run: `uv run pytest tests/test_security.py tests/test_release_gates.py -v`

Expected: CSRF, identity, rate limit, and fail-closed startup tests PASS

Run: `git grep -n -E '(X-User-Token.{0,20}[A-Za-z0-9]{16}|DFR_CONFIG_KEY=.+|INSTANCE_TOKEN=.+)' -- ':!docs/superpowers/**' ':!.env.example'`

Expected: no secret values found

- [ ] **Step 6: Capture deterministic UI evidence**

Start Mock mode locally and use Playwright at `1440x900` to capture:

- `artifacts/dfr-collapsed.png` at `0ms`
- `artifacts/dfr-mid-animation.png` at `110ms`
- `artifacts/dfr-expanded.png` at `220ms`
- `artifacts/dfr-mobile.png` at `390x844`

Compare rail width, panel offset, icons, colors, typography, and field copy against the supplied FH2 screenshots. Fix visual mismatches before publishing.

- [ ] **Step 7: Publish Mock mode to DreamCoder**

Invoke the `publish` skill from the project root. Select `instance_members`, classify the application as `sensitive` because it will hold encrypted FH2 test configuration and incident coordinates, and publish with live dispatch disabled.

Expected: DreamCoder URL loads, shows `MOCK MODE`, all three modules work, and non-members cannot access it

- [ ] **Step 8: Verify persistence and edge identity**

Save synthetic configuration, restart the service using DreamCoder's generated `.publish/start.sh`, and confirm the masked suffixes remain. Exercise the URL as an authorized member and through an unauthorized session. Record the trusted identity header name and proxy CIDRs without recording identity secrets.

- [ ] **Step 9: Run one authorized live smoke test only after every gate passes**

Set the verified deployment secrets, `FH2_CONTRACT_VERIFIED=true`, and `LIVE_DISPATCH_ENABLED=true`. Submit one synthetic priority-5 incident to the authorized test workflow. Confirm:

- one FH2 request
- HTTP outcome captured accurately
- one audit row
- no duplicate task after replaying the same idempotency key
- no plaintext token or full identifier in logs

Immediately return to Mock mode if the result is indeterminate or any security evidence fails.

- [ ] **Step 10: Commit deployment and verification assets**

Do not commit `.env`, SQLite data, platform-generated runtime files, or secrets. Commit only code, checklist, and non-sensitive screenshots.

```bash
git add publish.yml .env.example app tests docs/release-checklist.md artifacts
git commit -m "chore: add guarded DreamCoder release"
```

---

## Final Verification

- [ ] Run `git status --short` and confirm only intentionally uncommitted runtime files are ignored.
- [ ] Run `uv run pytest tests -v` and record the passing count.
- [ ] Run the Playwright suite at desktop and mobile sizes.
- [ ] Confirm the DreamCoder URL uses `instance_members` visibility.
- [ ] Confirm the deployed mode badge matches the release checklist result.
- [ ] Confirm no FH2 live request was sent before authorization and contract verification.
- [ ] Return the DreamCoder URL, screenshot paths, commit hashes, test output summary, and any release gate that remains Mock-only.
