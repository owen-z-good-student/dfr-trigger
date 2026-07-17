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
