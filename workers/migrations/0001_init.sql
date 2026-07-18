CREATE TABLE IF NOT EXISTS fh2_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  region TEXT NOT NULL CHECK (region IN ('global', 'eu')),
  user_token TEXT NOT NULL,
  project_uuid TEXT NOT NULL,
  workflow_uuid TEXT NOT NULL,
  creator_id TEXT,
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