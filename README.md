# DFR Trigger

> FH2-style DFR (Drone as First Responder) dispatch trigger — select a point on OSM map, trigger FH2 workflow dispatch via Public Cloud API, with encrypted config management and 7-day audit logging.

## Quick Start

```bash
cd dfr-trigger
uv sync --frozen --no-dev
cp .env.example .env
# Edit .env with your keys
uv run uvicorn app.main:app --host 0.0.0.0 --port 8081
```

Open `http://localhost:8081` in browser.

## Architecture

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12+ FastAPI |
| Frontend | Vanilla JS + CSS (no framework) |
| Map | Leaflet 1.9.4 (local vendor) + OSM tiles |
| Database | SQLite (WAL mode, 0600 perms) |
| Encryption | AES-256-GCM via cryptography |
| Validation | Pydantic v2 |
| Tests | pytest + RESPX + Playwright |

## .env Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `DFR_CONFIG_KEY` | Yes | URL-safe base64 32-byte AES key |
| `CSRF_SECRET` | Yes | HMAC key, min 32 chars |
| `FH2_BASE_URL` | Live only | FH2 Public Cloud API base URL |
| `FH2_API_KEY` | Live only | FH2 API Key |
| `LIVE_DISPATCH_ENABLED` | No | Set `true` for live mode |
| `DEV_MODE` | No | Set `true` to skip HTTPS gate locally |

## Release Gates

6 gates must pass before `LIVE_DISPATCH_ENABLED=true`:
1. `FH2_CONTRACT_VERIFIED=true`
2. `DFR_CONFIG_KEY` set (32-byte AES)
3. `CSRF_SECRET` ≥ 32 chars, not mock default
4. `PUBLIC_ORIGIN` starts with `https://` (skip with `DEV_MODE=true`)
5. `TRUSTED_IDENTITY_HEADER` set
6. `TRUSTED_PROXY_CIDRS` non-empty

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/bootstrap` | Set CSRF cookie |
| GET | `/api/config` | View config status (sanitized) |
| PUT | `/api/config` | Save/update config |
| POST | `/api/config/test` | Test config completeness |
| POST | `/api/dispatch` | Trigger dispatch (Idempotency-Key header) |
| GET | `/api/logs` | Audit logs (cursor pagination) |
| POST | `/api/geocode` | Address → coordinates |

## Testing

```bash
uv run --group dev pytest -q --ignore=tests/browser  # 125 tests
```

## License

Internal — DJI Industry Line