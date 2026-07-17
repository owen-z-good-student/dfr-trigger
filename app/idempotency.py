import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.db import Database
from app.redaction import sanitize


ReservationState = Literal["created", "processing", "completed", "conflict"]
RESULT_ENVELOPE_FIELDS = (
    "incident_id",
    "audit_id",
    "outcome",
    "http_status",
    "error_category",
    "replayed",
)
RESULT_MAX_BYTES = 65_536


@dataclass(frozen=True)
class Reservation:
    state: ReservationState
    result: dict | None = None
    generation: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _result_dict(result: object) -> dict:
    if isinstance(result, dict):
        return result
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError("idempotency result must be a dictionary or Pydantic model")


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()


def _serialize_result(
    result: object,
    sensitive_values: tuple[str, ...],
    max_bytes: int = RESULT_MAX_BYTES,
) -> str:
    sanitized = sanitize(_result_dict(result), sensitive_values)
    if not isinstance(sanitized, dict):
        raise TypeError("idempotency result must serialize to an object")

    encoded = _json_bytes(sanitized)
    if len(encoded) <= max_bytes:
        return encoded.decode("ascii")

    bounded = {
        field: sanitized[field]
        for field in RESULT_ENVELOPE_FIELDS
        if field in sanitized
    }
    if len(_json_bytes(bounded)) > max_bytes:
        raise ValueError("idempotency result envelope exceeds storage limit")

    for key, value in sanitized.items():
        if key in RESULT_ENVELOPE_FIELDS:
            continue
        candidate = {**bounded, key: value}
        if len(_json_bytes(candidate)) <= max_bytes:
            bounded[key] = value
            continue
        replacement = {
            "truncated": True,
            "original_bytes": len(_json_bytes(value)),
        }
        candidate = {**bounded, key: replacement}
        if len(_json_bytes(candidate)) <= max_bytes:
            bounded[key] = replacement

    return _json_bytes(bounded).decode("ascii")


class IdempotencyStore:
    def __init__(self, database: Database, retention_days: int):
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        self.database = database
        self.retention_days = retention_days

    def reserve(self, key: str, incident_id: str, fingerprint: str) -> Reservation:
        now = _utc_now()
        expires_at = now + timedelta(days=self.retention_days)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM idempotency WHERE idempotency_key=?", (key,)
            ).fetchone()
            if row is not None and row["expires_at"] <= now.isoformat():
                connection.execute(
                    "DELETE FROM dispatch_audit WHERE idempotency_key=?", (key,)
                )
                connection.execute(
                    "DELETE FROM idempotency WHERE idempotency_key=?", (key,)
                )
                row = None

            if row is None:
                generation = secrets.token_urlsafe(24)
                connection.execute(
                    """INSERT INTO idempotency (
                       idempotency_key, incident_id, request_fingerprint,
                       reservation_generation, audit_id, status, result_json,
                       created_at, expires_at
                       ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        key,
                        incident_id,
                        fingerprint,
                        generation,
                        None,
                        "processing",
                        None,
                        now.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
                reservation = Reservation("created", generation=generation)
            elif row["request_fingerprint"] != fingerprint:
                reservation = Reservation("conflict")
            elif row["status"] == "completed":
                reservation = Reservation(
                    "completed",
                    json.loads(row["result_json"])
                    if row["result_json"] is not None
                    else None,
                    row["reservation_generation"],
                )
            else:
                reservation = Reservation(
                    "processing", generation=row["reservation_generation"]
                )
            connection.commit()
            return reservation
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete(
        self,
        key: str,
        generation: str,
        result: object,
        sensitive_values: tuple[str, ...],
    ) -> None:
        serialized = _serialize_result(result, sensitive_values)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE idempotency
                   SET status='completed', result_json=?
                   WHERE idempotency_key=? AND reservation_generation=?
                     AND status='processing'""",
                (serialized, key, generation),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("stale idempotency reservation")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cleanup(self) -> int:
        now = _utc_now().isoformat()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """DELETE FROM dispatch_audit
                   WHERE idempotency_key IN (
                     SELECT idempotency_key FROM idempotency WHERE expires_at<=?
                   )""",
                (now,),
            )
            cursor = connection.execute(
                "DELETE FROM idempotency WHERE expires_at<=?", (now,)
            )
            connection.commit()
            return cursor.rowcount
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
