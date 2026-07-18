# Changelog

## v2.0.0 (in progress)

### Added
- Multi-language support (EN / PT) with top black bar
- Live stream module (FH2 share links)
- Task progress tracking with animated dashed line
- Real-time drone position on map via telemetry API
- Cloudflare Workers migration (Hono + D1 + KV)
- Event API webhook receiver (Cloudflare Worker)
- Brand logo upload in Config panel

### Changed
- "Configuration" renamed to "Config"
- Nav rail collapses to icons-only mode
- Log panel redesigned as scrollable debug panel (Dispatch + OpenAPI calls)
- Home base marker persists on map across interactions
- Coordinate input accepts comma decimal separator (Brazilian locale)
- FH2 longitude 0-360 format auto-converted to -180..180

### Removed
- Creator ID field from Config panel

## v1.0.0 (2026-07-14)

- Initial release
- OSM map with single-point dispatch
- FH2 Public Cloud workflow trigger
- AES-256-GCM encrypted config storage
- 7-day audit logging with cursor pagination
- CSRF protection, rate limiting, idempotency
- 6 release gates for live mode
- 125 backend tests (pytest + RESPX)
- 5 browser tests (Playwright)