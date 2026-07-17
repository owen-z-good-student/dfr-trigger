# DFR Trigger Design

## Purpose

Build a FlightHub 2-styled DFR trigger for an authorized FlightHub 2 Public Cloud test project. The application lets an instance member select an incident location on a map, submit a triggered workflow, manage the test-project configuration, and inspect seven days of sanitized request and response logs.

The product must feel visually native to FlightHub 2 while remaining clearly scoped as an integration tool. It must not copy protected DJI assets or expose FlightHub 2 credentials to the browser.

## Confirmed Scope

- Deployment: FlightHub 2 Public Cloud
- Environment: authorized FH2 test project only
- Hosting: DreamCoder with `instance_members` visibility
- Application login: none; DreamCoder provides the access gate
- Map: OpenStreetMap street tiles
- Backend: FastAPI
- Rendering: Jinja2, native CSS, and native JavaScript
- Storage: SQLite for configuration ciphertext, idempotency records, and audit logs
- Log retention: seven days
- Dispatch behavior: one click submits immediately
- Default priority: level 5
- Project path: `/home/opencode/vibe-coding/DFR Trigger`

## Out Of Scope

- Production FH2 projects
- Public anonymous access to a real FH2 trigger endpoint
- Drone telemetry, livestream, media synchronization, or mission status tracking
- CAD, VMS, GIS, or PSIM connectors
- Flight controls outside the documented Triggered Workflow capability
- Automatic retries after an FH2 timeout or server error
- Mobile-native applications

## User Experience

### Workspace

The application uses a full-viewport OpenStreetMap canvas. A dark FlightHub 2-inspired navigation rail and a dark functional panel sit on the left. The map occupies all remaining space.

Clicking the map places one incident marker and writes latitude and longitude into the Dispatch form. Manually changing valid coordinates moves the marker. Address geocoding is available as an optional helper and runs through the backend so browser clients do not call geocoding services directly.

If map tiles or geocoding are unavailable, coordinate entry and dispatch remain usable.

### Navigation Rail

The rail defaults to a collapsed width of `49px`. A hamburger button at the top expands it to `131px`. Expanded mode displays each module name to the right of its icon. Clicking the hamburger again returns it to icon-only mode.

The rail, functional panel, and map shift together. The panel does not overlay the map.

Initial animation parameters are:

- Duration: `220ms`
- Easing: `cubic-bezier(0.4, 0, 0.2, 1)`
- Animated properties: rail width, panel offset, map offset, and label opacity

These values are an implementation baseline inferred from supplied screenshots. The publicly accessible FlightHub 2 shell and bundles did not expose the micro-app's exact sidebar transition. Visual verification uses screenshot comparison. A future FlightHub 2 screen recording may be used for optional frame-level refinement without blocking the initial release.

The module icons use the Lucide icon family at `24px` with a `2px` stroke:

- Dispatch: `Drone`
- Configuration: `Wrench`
- Log: `BookOpen`

The selected module uses a FlightHub 2-style blue background. Inactive icons use a restrained gray-white stroke. Focus and hover states remain keyboard visible.

### Functional Panel

One `250px`-wide panel container is reused for all modules. Switching modules replaces panel content with a `150ms` opacity fade and does not stack drawers. Spacing, color, and typography are calibrated against the supplied FlightHub 2 screenshots.

### Dispatch

Required fields:

- Latitude: decimal number from `-90` through `90`
- Longitude: decimal number from `-180` through `180`
- Priority: integer from `1` through `5`, default `5`

Optional fields:

- Incident Type
- Description
- Location or address
- Operator Name
- Caller Phone

`Description` carries forward the old trigger's Additional Notes capability under the new label, avoiding two fields with duplicate meaning.

Incident Type is a select with:

- Security Alarm
- Fire
- Traffic Accident
- Crime in Progress
- Search & Rescue
- Missing Person
- Other

Selecting Other reveals a required custom incident-type text field. Leaving Incident Type blank is valid.

The Dispatch button is enabled only when required fields are valid and an FH2 configuration is active. A single click immediately submits. The UI disables the button while the request is in flight and shows a progress state. No confirmation modal is added.

### Configuration

Configuration transfers the old trigger's settings capability while moving secrets to the backend:

- API region: Global or Europe
- X-User-Token
- Project UUID
- Workflow UUID
- Creator ID
- Save Configuration
- Test Configuration

The target FH2 host is selected from a server-owned allowlist based on region. Users cannot enter an arbitrary API base URL.

The browser never receives a saved token. A configuration read returns only `Configured` or `Not configured` for the token. Project UUID, Workflow UUID, and Creator ID show only their final six characters in normal UI display. Replacing a value requires entering the complete new value.

Creator ID is editable because the official Triggered Workflow request requires the system-generated creator value shown by FlightHub 2. The input uses the manual's sample ID as placeholder text only. The application never generates a Creator ID and never treats the sample as a saved default. Real dispatch remains disabled until the user saves the actual Creator ID from the current FlightHub 2 workflow configuration.

Test Configuration must use a non-dispatching validation method confirmed by official FH2 documentation. If no safe validation endpoint is documented, the button validates format and storage only and explicitly states that no FH2 task was created. It must never send a synthetic flight trigger merely to test credentials.

### Log

Log transfers and expands the old trigger's incident history:

- Search by Incident ID, incident type, location, or operator
- Filter by priority
- Filter by success, failure, or indeterminate outcome
- View timestamp, duration, request body, response status, and response body
- Refresh the list

The application stores full business request and response bodies subject to recursive redaction and size limits. It never stores authentication headers or plaintext credentials. Project UUID values are masked in rendered audit metadata. Logs expire after seven days and are deleted on startup and by a scheduled daily cleanup.

## Architecture

```text
Browser
  -> DreamCoder instance-members access gate
  -> FastAPI application
       -> UI routes and static assets
       -> Dispatch API
            -> validation
            -> identity and CSRF checks
            -> rate limit and idempotency
            -> FH2 Public Cloud adapter
       -> Configuration API
            -> encrypted configuration store
       -> Log API
            -> SQLite audit store
       -> Geocoding adapter
            -> allowlisted OpenStreetMap-compatible provider
```

### Component Boundaries

`web` owns page rendering, static assets, and browser interactions. It does not know FH2 credentials.

`dispatch` validates the application request, resolves a trustworthy member identity, enforces rate limits and idempotency, calls the FH2 adapter once, and writes the audit result.

`fh2` owns the documented Public Cloud host, endpoint, authentication headers, timeout, and payload mapping. No other module calls FH2.

`config` encrypts and decrypts FH2 settings. It exposes status and masked metadata to the UI, never saved plaintext.

`audit` writes sanitized request and response records, queries filters, and deletes expired rows.

`geocoding` accepts address text, calls only a fixed allowlisted provider, applies a timeout and cache, and returns coordinates. It cannot follow redirects to arbitrary hosts.

## Data Model

### Encrypted Configuration

- Region
- Encrypted user token
- Encrypted project UUID
- Encrypted workflow UUID
- Encrypted creator ID
- Created timestamp
- Updated timestamp
- Updated-by member identity

The application uses AES-256-GCM with a random nonce per encrypted value. The encryption key is injected as a deployment secret and is never stored in the database, repository, image, or log.

### Dispatch Audit

- Internal audit UUID
- Incident ID
- Idempotency key
- Trusted member identity
- Submitted timestamp
- Completed timestamp
- Duration
- Region
- Sanitized request body
- HTTP status when received
- Sanitized response body
- Outcome: success, failure, or indeterminate
- Error category

### Idempotency Record

- Idempotency key with a unique constraint
- Incident ID
- Request fingerprint
- Processing status
- Stored result reference
- Created timestamp
- Expiry timestamp

## FH2 Request Mapping

The final endpoint, header casing, and body schema must be verified against the latest official Triggered Workflow documentation immediately before implementation. The old trigger currently uses the regional `/openapi/v0.1/workflow` pattern, `X-User-Token`, lowercase `x-project-uuid`, and a body containing `workflow_uuid`, `trigger_type`, `name`, and `params`. This is evidence from the existing implementation, not permission to assume the production contract is unchanged.

The application request maps business fields into only documented FH2 fields. Optional data that has no dedicated documented field is serialized into `desc` in a stable, readable order. The adapter rejects startup into live mode if schema verification has not been recorded.

No credential, project identifier, workflow identifier, endpoint, event type, or response field may be invented.

## Dispatch Data Flow

1. The browser validates visible fields and creates an Incident ID plus a random idempotency key.
2. The browser sends JSON with the CSRF token and idempotency key.
3. FastAPI validates exact schema, ranges, enums, string lengths, content type, origin, and CSRF token. Unknown fields are rejected.
4. FastAPI obtains a member identity from a platform header only after the DreamCoder proxy trust chain is verified. Client-supplied copies of that header are removed or ignored.
5. The rate limiter checks member, instance, and project limits.
6. The idempotency store inserts the key under a unique constraint. A duplicate with the same fingerprint returns the existing result. A duplicate with different content is rejected.
7. The configuration service decrypts settings in process memory.
8. The FH2 adapter sends one bounded request to the fixed regional host.
9. The audit service sanitizes and stores the business request and response.
10. The API returns the outcome to the browser and the Log module can display it immediately.

## Error Handling

- Missing configuration: Dispatch is disabled and Configuration is opened with a clear message.
- Invalid fields: Inline errors are shown and no request is sent.
- Duplicate submission: The original result is returned without a second FH2 call.
- FH2 authentication or permission error: The UI shows a concise failure and Log stores the sanitized response.
- FH2 validation error: The UI identifies the rejected request without exposing credentials.
- FH2 server error or timeout: The result is marked indeterminate when task creation cannot be ruled out. The application does not automatically retry.
- Network failure before a request can be sent: The result is marked failure.
- Audit storage unavailable: Real dispatch is blocked because an unaudited operation is not allowed.
- Map failure: Manual coordinates remain available.
- Geocoding failure: The user receives a non-blocking message and can use the map or coordinates.
- Encryption key missing or invalid: Configuration and dispatch routes fail closed.

## Security Controls

Controls required before enabling real test-project dispatch:

- Verify DreamCoder `instance_members` protects every UI and API route.
- Verify the backend origin cannot be reached while bypassing the DreamCoder access gate.
- Confirm the trusted member identity source and reject spoofable identity headers.
- Use same-origin requests, JSON-only state changes, Origin and Referer validation, and CSRF tokens.
- Use AES-256-GCM with deployment-secret key separation.
- Fix and allowlist FH2 and geocoding destinations; reject redirects to unapproved hosts.
- Enforce strict request schemas, string limits, coordinate ranges, and enum values.
- Enforce idempotency under a database unique constraint.
- Apply per-member, per-instance, and per-project rate and concurrency limits.
- Recursively redact token-like keys and credentials before logging.
- Truncate oversized request and response values with an explicit truncation marker.
- Use a least-privilege, revocable FH2 test-project credential.
- Keep secrets and runtime data out of Git.

If DreamCoder access enforcement, trusted identity, persistent runtime storage, or deployment-secret injection cannot be verified, the deployed build remains Mock-only.

## Testing Strategy

### Unit Tests

- Required and optional field validation
- Incident Type Other behavior
- Priority defaults to 5
- FH2 payload construction from every field combination
- AES-GCM encryption, decryption, and wrong-key failure
- Recursive log redaction and response truncation
- Seven-day retention cleanup
- Idempotency key uniqueness and request fingerprint conflicts
- Regional host allowlist
- Rate-limit decisions

### Integration Tests

A local mock FH2 server covers:

- Success
- Invalid request
- Invalid token
- Forbidden project
- Unknown workflow
- Server error
- Connection failure
- Timeout and indeterminate outcome
- Duplicate browser submissions producing one upstream call

### Browser Tests

- Navigation defaults to collapsed
- Hamburger expands and collapses labels
- Rail, panel, and map move together
- Drone, Wrench, and BookOpen icons render at the specified size
- Module switching reuses one functional panel
- Map click fills coordinates and places one marker
- Manual coordinates move the marker
- Incident Type Other reveals its text field
- Description and all carried-forward optional fields submit correctly
- Priority begins at 5
- Dispatch locks during submission
- Configuration never renders a saved plaintext token
- Log filters and detail views work
- Keyboard navigation and focus states remain usable
- Desktop and mobile layouts do not lose required controls

### Visual Verification

- Capture fixed-size screenshots for collapsed and expanded navigation states.
- Compare rail widths, panel position, colors, icon geometry, typography, spacing, and map controls with supplied FlightHub 2 references.
- Capture the navigation animation at `0ms`, `110ms`, and `220ms` with Playwright.
- Treat protected DJI icons and assets as references only; use the selected Lucide icons.

### Security Negative Tests

- Anonymous and non-member requests are rejected by the deployment gate.
- Direct backend-origin access is rejected.
- Forged member identity headers do not create trusted audit identities.
- Missing or cross-origin CSRF submissions are rejected.
- Arbitrary target URLs and redirect-based SSRF attempts are rejected.
- Double-clicks and replayed idempotency keys do not create duplicate FH2 calls.
- Logs contain no plaintext token, authentication header, encryption key, or unmasked secret field.

### Authorized Live Smoke Test

After official schema verification and safety authorization, submit one synthetic event to the authorized FH2 Public Cloud test project. Verify the FH2 response, the single audit entry, the absence of secrets in logs, and the lack of a duplicate task.

## Project And Delivery

The new project is an independent Git repository at `/home/opencode/vibe-coding/DFR Trigger`.

It receives project-level OpenCode configuration and Superpowers `v6.1.1`, based on the parent workspace setup. Global OpenCode configuration and the Mac are not modified.

The delivery contains:

- Source code and tests
- Project-level Superpowers configuration
- DreamCoder deployment configuration with `instance_members` visibility
- A DreamCoder access URL
- Collapsed and expanded UI screenshots
- Verification results and remaining evidence gaps

## Release Gates

The application can enable real FH2 test dispatch only when all gates pass:

- Official Triggered Workflow endpoint, headers, and schema are verified.
- FH2 test-project authorization is confirmed.
- DreamCoder instance-member enforcement covers UI and API routes.
- Backend origin bypass is blocked.
- Trusted user identity is available for audit.
- Deployment-secret injection works.
- SQLite and encrypted configuration persist across an application restart.
- Unit, integration, browser, and security negative tests pass.

Failure of any gate produces a Mock-only deployment with a visible non-production indicator.
