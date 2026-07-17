import asyncio
import json
import logging
import sqlite3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.audit_store import AuditStore
from app.db import Database
from app.idempotency import IdempotencyStore
from app.main import create_app
from app.maintenance import cleanup_loop
from app.redaction import serialize_sanitized
from app.settings import Settings


def test_recursive_redaction_masks_keys_identifiers_and_exact_values():
    value = {
        "X-User-Token": "secret",
        "nested": {
            "password": "hidden",
            "project_uuid": "project-123456",
        },
        "description": "safe token-secret and xy must disappear",
    }

    result = json.loads(
        serialize_sanitized(value, sensitive_values=("token-secret", "xy"))
    )

    assert result["X-User-Token"] == "[REDACTED]"
    assert result["nested"]["password"] == "[REDACTED]"
    assert result["nested"]["project_uuid"].endswith("123456")
    assert "project" not in result["nested"]["project_uuid"]
    assert result["description"] == (
        "safe [REDACTED_VALUE] and [REDACTED_VALUE] must disappear"
    )


def test_redaction_handles_auth_aes_and_sensitive_keys_without_masking_author():
    sensitive = "project-123456"
    value = {
        "auth": "secret-a",
        "X-Auth": "secret-b",
        "x_auth": "secret-b2",
        "authHeader": "secret-c",
        "aes_key": "secret-d",
        "aesKey": "secret-d2",
        "AES-Key": "secret-d3",
        "nested": {
            "authorization_status": "secret-e",
            "author": "Synthetic Author",
            "author_name": "Synthetic Writer",
        },
        f"response-{sensitive}-id": "safe metadata",
    }

    serialized = serialize_sanitized(value, sensitive_values=(sensitive,))
    result = json.loads(serialized)

    assert result["auth"] == "[REDACTED]"
    assert result["X-Auth"] == "[REDACTED]"
    assert result["x_auth"] == "[REDACTED]"
    assert result["authHeader"] == "[REDACTED]"
    assert result["aes_key"] == "[REDACTED]"
    assert result["aesKey"] == "[REDACTED]"
    assert result["AES-Key"] == "[REDACTED]"
    assert result["nested"]["authorization_status"] == "[REDACTED]"
    assert result["nested"]["author"] == "Synthetic Author"
    assert result["nested"]["author_name"] == "Synthetic Writer"
    assert result["response-[REDACTED_VALUE]-id"] == "safe metadata"
    assert sensitive not in serialized


def test_oversized_serialization_is_valid_json_within_byte_limit():
    serialized = serialize_sanitized({"body": "x" * 100_000})

    result = json.loads(serialized)

    assert len(serialized.encode()) <= 65_536
    assert result["truncated"] is True
    assert result["original_bytes"] > 65_536
    assert isinstance(result["preview"], str)


def test_idempotency_same_fingerprint_replays_existing(database):
    store = IdempotencyStore(database, retention_days=7)

    first = store.reserve("key-1", "INC-SYNTHETIC-1", "hash-a")
    second = store.reserve("key-1", "INC-SYNTHETIC-1", "hash-a")
    conflict = store.reserve("key-1", "INC-SYNTHETIC-1", "hash-b")

    assert first.state == "created"
    assert first.generation
    assert second.state == "processing"
    assert second.generation == first.generation
    assert conflict.state == "conflict"
    assert conflict.generation is None


def test_idempotency_completed_reservation_replays_stored_result(database):
    store = IdempotencyStore(database, retention_days=7)
    result = {"outcome": "success", "incident_id": "INC-SYNTHETIC-2"}
    reservation = store.reserve("key-2", "INC-SYNTHETIC-2", "hash-a")

    store.complete("key-2", reservation.generation, result, sensitive_values=())

    replay = store.reserve("key-2", "INC-SYNTHETIC-2", "hash-a")
    assert replay.state == "completed"
    assert replay.result == result


def test_idempotency_result_preserves_sanitized_envelope_with_bounded_details(
    database,
):
    store = IdempotencyStore(database, retention_days=7)
    reservation = store.reserve("key-bounded", "INC-SYNTHETIC-6", "hash-a")
    sensitive = "synthetic-token-secret"

    store.complete(
        "key-bounded",
        reservation.generation,
        {
            "incident_id": "INC-SYNTHETIC-6",
            "audit_id": "audit-synthetic-6",
            "outcome": "failure",
            "http_status": 502,
            "error_category": f"upstream failure for {sensitive}",
            "replayed": False,
            "body": {"message": f"{sensitive}:" + "x" * 100_000},
            "diagnostic": {"raw": "y" * 100_000},
        },
        sensitive_values=(sensitive,),
    )

    with database.connect() as connection:
        serialized = connection.execute(
            "SELECT result_json FROM idempotency WHERE idempotency_key=?",
            ("key-bounded",),
        ).fetchone()["result_json"]
    stored = json.loads(serialized)
    assert len(serialized.encode()) <= 65_536
    assert sensitive not in serialized
    assert stored["incident_id"] == "INC-SYNTHETIC-6"
    assert stored["audit_id"] == "audit-synthetic-6"
    assert stored["outcome"] == "failure"
    assert stored["http_status"] == 502
    assert stored["error_category"] == "upstream failure for [REDACTED_VALUE]"
    assert stored["replayed"] is False
    assert stored["body"]["truncated"] is True
    assert stored["diagnostic"]["truncated"] is True

    replay = store.reserve("key-bounded", "INC-SYNTHETIC-6", "hash-a")
    assert replay.state == "completed"
    assert replay.result == stored


@pytest.mark.parametrize("replacement_fingerprint", ["hash-same", "hash-different"])
def test_expired_reuse_rejects_stale_generation_and_releases_audit_key(
    database, replacement_fingerprint
):
    store = IdempotencyStore(database, retention_days=7)
    audits = AuditStore(database)
    old = store.reserve("key-reused", "INC-SYNTHETIC-7", "hash-same")
    old_audit_id = audits.create_pending(
        synthetic_request(7), "old-worker", "key-reused", "eu", ()
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE idempotency SET expires_at=? WHERE idempotency_key=?",
            ("2000-01-01T00:00:00+00:00", "key-reused"),
        )
        connection.execute(
            "UPDATE dispatch_audit SET submitted_at=? WHERE audit_id=?",
            ("2000-01-01T00:00:00+00:00", old_audit_id),
        )

    replacement = store.reserve(
        "key-reused", "INC-SYNTHETIC-7", replacement_fingerprint
    )
    replacement_audit_id = audits.create_pending(
        synthetic_request(7), "new-worker", "key-reused", "eu", ()
    )

    assert old.generation != replacement.generation
    with pytest.raises(RuntimeError, match="stale idempotency reservation"):
        store.complete(
            "key-reused",
            old.generation,
            {"outcome": "failure", "worker": "old"},
            sensitive_values=(),
        )

    new_result = {"outcome": "success", "worker": "new"}
    store.complete(
        "key-reused",
        replacement.generation,
        new_result,
        sensitive_values=(),
    )
    replay = store.reserve(
        "key-reused", "INC-SYNTHETIC-7", replacement_fingerprint
    )
    assert replay.state == "completed"
    assert replay.result == new_result
    with database.connect() as connection:
        audit_ids = [
            row["audit_id"]
            for row in connection.execute(
                "SELECT audit_id FROM dispatch_audit WHERE idempotency_key=?",
                ("key-reused",),
            )
        ]
    assert audit_ids == [replacement_audit_id]


def test_new_reservation_does_not_delete_audit_without_expired_reservation(database):
    audits = AuditStore(database)
    audit_id = audits.create_pending(
        synthetic_request(8), "existing-worker", "key-existing-audit", "eu", ()
    )

    reservation = IdempotencyStore(database, retention_days=7).reserve(
        "key-existing-audit", "INC-SYNTHETIC-8", "hash-a"
    )

    assert reservation.state == "created"
    with database.connect() as connection:
        stored_audit = connection.execute(
            "SELECT audit_id FROM dispatch_audit WHERE idempotency_key=?",
            ("key-existing-audit",),
        ).fetchone()
    assert stored_audit["audit_id"] == audit_id


def test_idempotency_reservation_is_atomic_across_sqlite_connections(database):
    workers = 8
    barrier = Barrier(workers)

    def reserve() -> str:
        barrier.wait()
        return IdempotencyStore(database, retention_days=7).reserve(
            "key-concurrent", "INC-SYNTHETIC-3", "hash-a"
        ).state

    with ThreadPoolExecutor(max_workers=workers) as executor:
        states = list(executor.map(lambda _: reserve(), range(workers)))

    assert Counter(states) == {"created": 1, "processing": workers - 1}


def test_idempotency_cleanup_removes_only_expired_rows(database):
    store = IdempotencyStore(database, retention_days=7)
    store.reserve("key-expired", "INC-SYNTHETIC-4", "hash-a")
    store.reserve("key-current", "INC-SYNTHETIC-5", "hash-b")
    audits = AuditStore(database)
    expired_audit_id = audits.create_pending(
        synthetic_request(4), "actor-expired", "key-expired", "eu", ()
    )
    current_audit_id = audits.create_pending(
        synthetic_request(5), "actor-current", "key-current", "eu", ()
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE idempotency SET expires_at=? WHERE idempotency_key=?",
            ("2000-01-01T00:00:00+00:00", "key-expired"),
        )
        connection.execute(
            "UPDATE idempotency SET expires_at=? WHERE idempotency_key=?",
            ("2999-01-01T00:00:00+00:00", "key-current"),
        )

    assert store.cleanup() == 1

    with database.connect() as connection:
        keys = {
            row["idempotency_key"]
            for row in connection.execute("SELECT idempotency_key FROM idempotency")
        }
        audit_ids = {
            row["audit_id"]
            for row in connection.execute("SELECT audit_id FROM dispatch_audit")
        }
    assert keys == {"key-current"}
    assert audit_ids == {current_audit_id}
    assert expired_audit_id not in audit_ids


def test_database_initialize_migrates_existing_idempotency_generations(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """CREATE TABLE idempotency (
               idempotency_key TEXT PRIMARY KEY,
               incident_id TEXT NOT NULL,
               request_fingerprint TEXT NOT NULL,
               audit_id TEXT,
               status TEXT NOT NULL CHECK (status IN ('processing','completed')),
               result_json TEXT,
               created_at TEXT NOT NULL,
               expires_at TEXT NOT NULL
               );
               INSERT INTO idempotency VALUES (
                 'legacy-key', 'INC-SYNTHETIC-LEGACY', 'hash-legacy', NULL,
                 'processing', NULL, '2026-07-01T00:00:00+00:00',
                 '2026-07-20T00:00:00+00:00'
               );"""
        )

    database = Database(path)
    database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(idempotency)")
        }
        generation = connection.execute(
            "SELECT reservation_generation FROM idempotency WHERE idempotency_key=?",
            ("legacy-key",),
        ).fetchone()["reservation_generation"]
    assert "reservation_generation" in columns
    assert generation


def test_database_initialize_repairs_partially_migrated_generation(tmp_path):
    path = tmp_path / "partially-migrated.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """CREATE TABLE idempotency (
               idempotency_key TEXT PRIMARY KEY,
               incident_id TEXT NOT NULL,
               request_fingerprint TEXT NOT NULL,
               reservation_generation TEXT,
               audit_id TEXT,
               status TEXT NOT NULL CHECK (status IN ('processing','completed')),
               result_json TEXT,
               created_at TEXT NOT NULL,
               expires_at TEXT NOT NULL
               );
               INSERT INTO idempotency VALUES (
                 'partial-key', 'INC-SYNTHETIC-PARTIAL', 'hash-partial', NULL,
                 NULL, 'processing', NULL, '2026-07-01T00:00:00+00:00',
                 '2026-07-20T00:00:00+00:00'
               );"""
        )

    database = Database(path)
    database.initialize()
    database.initialize()

    with database.connect() as connection:
        generation = connection.execute(
            "SELECT reservation_generation FROM idempotency WHERE idempotency_key=?",
            ("partial-key",),
        ).fetchone()["reservation_generation"]
    assert generation


def test_database_initialize_closes_connection(tmp_path, monkeypatch):
    database = Database(tmp_path / "closed-after-initialize.db")
    connection = database.connect()
    monkeypatch.setattr(database, "connect", lambda: connection)

    database.initialize()

    try:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    finally:
        connection.close()


def synthetic_request(number: int, **overrides) -> dict:
    request = {
        "incident_id": f"INC-SYNTHETIC-{number}",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "priority": 5,
        "incident_type": "Fire",
        "location": "Paris Test Site",
        "operator_name": "Synthetic Operator",
        "description": "Synthetic audit record",
    }
    request.update(overrides)
    return request


def test_audit_pending_and_completion_are_sanitized(database):
    store = AuditStore(database)
    sensitive_values = (
        "token-secret",
        "project-123456",
        "workflow-123456",
        "creator-123456",
    )
    request = synthetic_request(
        10,
        description="Includes token-secret and workflow-123456",
        project_uuid="project-123456",
        X_User_Token="token-secret",
    )

    audit_id = store.create_pending(
        request,
        actor="synthetic-user",
        idempotency_key="audit-key-10",
        region="eu",
        sensitive_values=sensitive_values,
    )

    with database.connect() as connection:
        pending = connection.execute(
            "SELECT * FROM dispatch_audit WHERE audit_id=?", (audit_id,)
        ).fetchone()
    assert pending["outcome"] == "pending"
    assert pending["priority"] == 5
    assert pending["incident_type"] == "Fire"
    assert "token-secret" not in pending["request_json"]
    assert "project-123456" not in pending["request_json"]
    assert "workflow-123456" not in pending["request_json"]

    store.complete(
        audit_id,
        {
            "outcome": "success",
            "http_status": 200,
            "body": {"message": "Accepted creator-123456 with token-secret"},
            "error_category": None,
        },
        duration_ms=23,
        sensitive_values=sensitive_values,
    )

    with database.connect() as connection:
        completed = connection.execute(
            "SELECT * FROM dispatch_audit WHERE audit_id=?", (audit_id,)
        ).fetchone()
    assert completed["outcome"] == "success"
    assert completed["http_status"] == 200
    assert completed["duration_ms"] == 23
    assert completed["completed_at"] is not None
    assert "creator-123456" not in completed["response_json"]
    assert "token-secret" not in completed["response_json"]


@pytest.mark.parametrize(
    ("query", "expected_incident"),
    [
        ("INC-SYNTHETIC-21", "INC-SYNTHETIC-21"),
        ("search and rescue", "INC-SYNTHETIC-21"),
        ("Lyon", "INC-SYNTHETIC-21"),
        ("Operator Bob", "INC-SYNTHETIC-21"),
    ],
)
def test_audit_list_searches_supported_fields(database, query, expected_incident):
    store = AuditStore(database)
    store.create_pending(
        synthetic_request(20), "actor-a", "audit-key-20", "eu", ()
    )
    store.create_pending(
        synthetic_request(
            21,
            incident_type="Search and Rescue",
            location="Lyon Test Site",
            operator_name="Operator Bob",
        ),
        "actor-b",
        "audit-key-21",
        "eu",
        (),
    )

    page = store.list(query=query, limit=100)

    assert [item["incident_id"] for item in page["items"]] == [expected_incident]


def test_audit_list_filters_and_paginates_without_duplicates(database):
    store = AuditStore(database)
    audit_ids = []
    for number in (30, 31, 32):
        audit_id = store.create_pending(
            synthetic_request(number),
            f"actor-{number}",
            f"audit-key-{number}",
            "eu",
            (),
        )
        store.complete(
            audit_id,
            {
                "outcome": "success" if number != 31 else "failure",
                "http_status": 200 if number != 31 else 400,
                "body": {"synthetic": number},
                "error_category": None if number != 31 else "validation",
            },
            duration_ms=number,
            sensitive_values=(),
        )
        audit_ids.append(audit_id)
    with database.connect() as connection:
        for index, audit_id in enumerate(audit_ids):
            connection.execute(
                "UPDATE dispatch_audit SET submitted_at=? WHERE audit_id=?",
                (f"2026-07-14T10:0{index}:00+00:00", audit_id),
            )

    first = store.list(priority=5, outcome="success", limit=1)
    second = store.list(
        priority=5, outcome="success", limit=1, cursor=first["next_cursor"]
    )

    incidents = [first["items"][0]["incident_id"], second["items"][0]["incident_id"]]
    assert incidents == ["INC-SYNTHETIC-32", "INC-SYNTHETIC-30"]
    assert first["next_cursor"] is not None
    assert second["next_cursor"] is None


@pytest.mark.parametrize("query", ["%", "_"])
def test_audit_list_treats_wildcards_as_literal_text(database, query):
    store = AuditStore(database)
    store.create_pending(
        synthetic_request(33, location="Literal 100% Sector_A"),
        "actor-literal",
        "audit-key-33",
        "eu",
        (),
    )
    store.create_pending(
        synthetic_request(34, location="Literal 100X SectorZA"),
        "actor-control",
        "audit-key-34",
        "eu",
        (),
    )

    page = store.list(query=query, limit=100)

    assert [item["incident_id"] for item in page["items"]] == [
        "INC-SYNTHETIC-33"
    ]


def test_audit_list_rejects_malformed_cursor(database):
    with pytest.raises(ValueError, match="invalid audit cursor"):
        AuditStore(database).list(cursor="not-a-valid-cursor!")


@pytest.mark.parametrize("limit", [0, 101])
def test_audit_list_rejects_out_of_range_limit(database, limit):
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        AuditStore(database).list(limit=limit)


def test_audit_list_does_not_expose_pending_filter(database):
    with pytest.raises(ValueError, match="invalid audit outcome"):
        AuditStore(database).list(outcome="pending")


def test_audit_cleanup_removes_only_rows_older_than_retention(database):
    store = AuditStore(database)
    expired_id = store.create_pending(
        synthetic_request(40), "actor-old", "audit-key-40", "eu", ()
    )
    current_id = store.create_pending(
        synthetic_request(41), "actor-current", "audit-key-41", "eu", ()
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE dispatch_audit SET submitted_at=? WHERE audit_id=?",
            ("2000-01-01T00:00:00+00:00", expired_id),
        )
        connection.execute(
            "UPDATE dispatch_audit SET submitted_at=? WHERE audit_id=?",
            ("2999-01-01T00:00:00+00:00", current_id),
        )

    assert store.cleanup(retention_days=7) == 1

    with database.connect() as connection:
        remaining = connection.execute(
            "SELECT audit_id FROM dispatch_audit"
        ).fetchall()
    assert [row["audit_id"] for row in remaining] == [current_id]


def test_audit_create_pending_propagates_storage_failure(database, monkeypatch):
    def fail_connect():
        raise sqlite3.OperationalError("synthetic database failure")

    monkeypatch.setattr(database, "connect", fail_connect)

    with pytest.raises(sqlite3.OperationalError, match="synthetic database failure"):
        AuditStore(database).create_pending(
            synthetic_request(50), "actor", "audit-key-50", "eu", ()
        )


def test_audit_complete_sanitizes_error_category(database):
    store = AuditStore(database)
    sensitive = "synthetic-token-secret"
    audit_id = store.create_pending(
        synthetic_request(51), "actor", "audit-key-51", "eu", (sensitive,)
    )

    store.complete(
        audit_id,
        {
            "outcome": "failure",
            "http_status": 401,
            "body": {"detail": "synthetic failure"},
            "error_category": f"authorization failed for {sensitive}",
        },
        duration_ms=5,
        sensitive_values=(sensitive,),
    )

    with database.connect() as connection:
        category = connection.execute(
            "SELECT error_category FROM dispatch_audit WHERE audit_id=?", (audit_id,)
        ).fetchone()["error_category"]
    assert category == "authorization failed for [REDACTED_VALUE]"
    assert sensitive not in category


@pytest.mark.asyncio
async def test_cleanup_loop_runs_both_stores_before_sleeping_one_day(monkeypatch):
    calls = []

    class SyntheticAuditStore:
        def cleanup(self, retention_days):
            calls.append(("audit", retention_days))

    class SyntheticIdempotencyStore:
        def cleanup(self):
            calls.append(("idempotency", None))

    async def stop_after_first_sleep(seconds):
        calls.append(("sleep", seconds))
        raise asyncio.CancelledError

    monkeypatch.setattr("app.maintenance.asyncio.sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        await cleanup_loop(SyntheticAuditStore(), SyntheticIdempotencyStore(), 7)

    assert calls == [("audit", 7), ("idempotency", None), ("sleep", 86_400)]


@pytest.mark.parametrize("failing_store", ["audit", "idempotency"])
@pytest.mark.asyncio
async def test_cleanup_loop_logs_failure_and_retries_after_one_day(
    monkeypatch, caplog, failing_store
):
    calls = Counter()

    class SyntheticAuditStore:
        def cleanup(self, retention_days):
            assert retention_days == 7
            calls["audit"] += 1
            if failing_store == "audit" and calls["audit"] == 1:
                raise RuntimeError("synthetic audit cleanup failure")

    class SyntheticIdempotencyStore:
        def cleanup(self):
            calls["idempotency"] += 1
            if failing_store == "idempotency" and calls["idempotency"] == 1:
                raise RuntimeError("synthetic idempotency cleanup failure")

    async def sleep_twice(seconds):
        assert seconds == 86_400
        calls["sleep"] += 1
        if calls["sleep"] == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("app.maintenance.asyncio.sleep", sleep_twice)

    with caplog.at_level(logging.ERROR, logger="app.maintenance"):
        with pytest.raises(asyncio.CancelledError):
            await cleanup_loop(SyntheticAuditStore(), SyntheticIdempotencyStore(), 7)

    assert calls == {"audit": 2, "idempotency": 2, "sleep": 2}
    assert f"{failing_store} cleanup failed" in caplog.text
    assert f"synthetic {failing_store} cleanup failure" in caplog.text


def test_startup_runs_cleanup_and_exposes_stores(tmp_path, monkeypatch):
    calls = Counter()

    def audit_cleanup(self, retention_days):
        assert retention_days == 7
        calls["audit"] += 1
        return 0

    def idempotency_cleanup(self):
        calls["idempotency"] += 1
        return 0

    monkeypatch.setattr(AuditStore, "cleanup", audit_cleanup)
    monkeypatch.setattr(IdempotencyStore, "cleanup", idempotency_cleanup)
    app = create_app(Settings(data_dir=tmp_path, log_retention_days=7))

    with TestClient(app):
        assert isinstance(app.state.audit_store, AuditStore)
        assert isinstance(app.state.idempotency_store, IdempotencyStore)

    assert calls["audit"] >= 1
    assert calls["idempotency"] >= 1
