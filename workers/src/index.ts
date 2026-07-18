import { Hono } from "hono";
import { cors } from "hono/cors";
import { serveStatic } from "hono/cloudflare-workers";

type Env = {
  DB: D1Database;
  KV: KVNamespace;
  ENVIRONMENT: string;
  DFR_CONFIG_KEY?: string;
  CSRF_SECRET?: string;
  PUBLIC_ORIGIN?: string;
  FH2_BASE_URL?: string;
  FH2_API_KEY?: string;
};

const app = new Hono<{ Bindings: Env }>();

// ── CORS ──
app.use("*", cors());

// ── Static files ──
app.get("/static/*", serveStatic({ root: "./" }));

// ── API Routes ──

// Health
app.get("/api/health", (c) => c.json({ status: "ok", mode: "mock" }));

// Bootstrap (CSRF)
app.get("/api/bootstrap", (c) => {
  const token = crypto.randomUUID();
  c.header("Set-Cookie", `dfr_csrf=${token}; Max-Age=3600; Path=/; SameSite=Strict`);
  return c.json({ mode: "mock" });
});

// Config
app.get("/api/config", async (c) => {
  const row = await c.env.DB.prepare("SELECT * FROM fh2_config WHERE id=1").first();
  if (!row) return c.json({ token_configured: false });
  return c.json({
    region: row.region,
    token_configured: true,
    project_uuid_suffix: (row.project_uuid as string).slice(-6),
    workflow_uuid_suffix: (row.workflow_uuid as string).slice(-6),
  });
});

app.put("/api/config", async (c) => {
  const body = await c.req.json();
  const now = new Date().toISOString();
  await c.env.DB.prepare(`
    INSERT INTO fh2_config (id, region, user_token, project_uuid, workflow_uuid, creator_id, created_at, updated_at, updated_by)
    VALUES (1, ?, ?, ?, ?, NULL, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET region=excluded.region, user_token=excluded.user_token,
    project_uuid=excluded.project_uuid, workflow_uuid=excluded.workflow_uuid,
    updated_at=excluded.updated_at, updated_by=excluded.updated_by
  `).bind(body.region, body.user_token, body.project_uuid, body.workflow_uuid, now, now, "user").run();
  return c.json({ region: body.region, token_configured: true });
});

app.post("/api/config/test", async (c) => {
  const row = await c.env.DB.prepare("SELECT * FROM fh2_config WHERE id=1").first();
  if (!row) return c.json({ valid: false }, 503);
  return c.json({ valid: true, fh2_request_sent: false });
});

// Dispatch
app.post("/api/dispatch", async (c) => {
  const body = await c.req.json();
  const idempotencyKey = c.req.header("Idempotency-Key");
  if (!idempotencyKey) return c.json({ detail: "Idempotency-Key header required" }, 400);

  const config = await c.env.DB.prepare("SELECT * FROM fh2_config WHERE id=1").first();
  if (!config) return c.json({ detail: "FH2 configuration is incomplete" }, 503);

  const incidentId = body.incident_id || `INC-${Date.now().toString(36)}`;
  const auditId = crypto.randomUUID();
  const now = new Date().toISOString();

  await c.env.DB.prepare(`
    INSERT INTO dispatch_audit (audit_id, incident_id, idempotency_key, actor, priority,
      incident_type, location, operator_name, submitted_at, region, request_json, outcome)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(auditId, incidentId, idempotencyKey, "user", body.priority || 5,
    body.incident_type || null, body.location || null, body.operator_name || null,
    now, config.region as string, JSON.stringify(body), "pending").run();

  // Mock response
  await c.env.DB.prepare(`
    UPDATE dispatch_audit SET completed_at=?, outcome=?, http_status=?, response_json=?
    WHERE audit_id=?
  `).bind(now, "success", 200, JSON.stringify({ accepted: true, mock: true }), auditId).run();

  return c.json({
    incident_id: incidentId,
    audit_id: auditId,
    outcome: "success",
    http_status: 200,
    body: { accepted: true, mock: true },
    replayed: false,
  });
});

// Logs
app.get("/api/logs", async (c) => {
  const limit = Math.min(parseInt(c.req.query("limit") || "50"), 100);
  const rows = await c.env.DB.prepare(
    "SELECT * FROM dispatch_audit ORDER BY submitted_at DESC LIMIT ?"
  ).bind(limit + 1).all();
  const items = (rows.results || []).slice(0, limit).map((row: any) => ({
    ...row,
    request: JSON.parse(row.request_json || "{}"),
    response: row.response_json ? JSON.parse(row.response_json as string) : null,
  }));
  return c.json({ items, next_cursor: null });
});

// Webhook receiver (Event API)
app.post("/webhook/fh2", async (c) => {
  const body = await c.req.json();
  const eventType = body.event || "unknown";
  const incidentId = body.incident_id || body.task_id || "unknown";
  await c.env.KV.put(`task:${incidentId}`, JSON.stringify({
    ...body,
    received_at: new Date().toISOString(),
  }));
  return c.json({ ok: true });
});

// Task status (polled by frontend)
app.get("/api/tasks/:incident_id/status", async (c) => {
  const incidentId = c.req.param("incident_id");
  const data = await c.env.KV.get(`task:${incidentId}`);
  if (!data) return c.json({ status: "pending" });
  return c.json(JSON.parse(data));
});

// Live shares
app.get("/api/live", async (c) => {
  return c.json({ shares: [] });
});

// SPA fallback
app.get("*", serveStatic({ path: "./app/templates/index.html" }));

export default app;