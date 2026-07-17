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
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.path}{suffix}")
            if sidecar.exists():
                sidecar.chmod(0o600)
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
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
                # Migration: make creator_id nullable (run once, preserve existing data)
                fh2_columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(fh2_config)")}
                creator_col = fh2_columns.get("creator_id")
                if creator_col and creator_col["notnull"]:
                    connection.execute("ALTER TABLE fh2_config RENAME TO __fh2_config_old")
                    connection.executescript(SCHEMA)
                    connection.execute(
                        """INSERT INTO fh2_config (id, region, user_token, project_uuid, workflow_uuid, creator_id, created_at, updated_at, updated_by)
                           SELECT id, region, user_token, project_uuid, workflow_uuid, creator_id, created_at, updated_at, updated_by
                           FROM __fh2_config_old"""
                    )
                    connection.execute("DROP TABLE __fh2_config_old")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        self.path.chmod(0o600)
