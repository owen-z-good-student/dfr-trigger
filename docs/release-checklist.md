# DFR Trigger Release Checklist

## Access boundary

- [ ] DreamCoder application visibility is `instance_members`
- [ ] Anonymous UI and API requests are rejected at the edge
- [ ] Direct backend-origin access is unavailable
- [ ] Public clients cannot spoof the trusted member identity header
- [ ] Uvicorn starts with `--no-proxy-headers`

## Secrets and persistence

- [ ] `DFR_CONFIG_KEY` is injected as a deployment secret
- [ ] `CSRF_SECRET` differs from the Mock default
- [ ] `.env`, SQLite data, tokens, and full identifiers are absent from Git and logs
- [ ] Encrypted configuration and SQLite audit data persist after restart

## FH2 test authorization

- [ ] Full Public Cloud Triggered Workflow URL is verified from a current authorized source
- [ ] Project UUID, Workflow UUID, and Creator ID come from the same FH2 test project
- [ ] FH2 token is revocable and scoped to the authorized test project
- [ ] One synthetic priority-5 event is approved for smoke testing

## Automated evidence

- [ ] Backend and browser test suites pass
- [ ] CSRF, origin, identity, rate limit, idempotency, and redaction negative tests pass
- [ ] Collapsed, expanded, mid-animation, and mobile screenshots are reviewed
- [ ] Replay of one Idempotency-Key creates exactly one FH2 request

## Release decision

If any item is unchecked, keep `LIVE_DISPATCH_ENABLED=false` and display `MOCK MODE`
