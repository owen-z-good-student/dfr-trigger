from typing import Optional
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

from app.db import Database
from app.redaction import sanitize, serialize_sanitized


AUDIT_OUTCOMES = {"pending", "success", "failure", "indeterminate"}
FILTERABLE_OUTCOMES = AUDIT_OUTCOMES - {"pending"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError("audit value must be a dictionary or Pydantic model")


def _sanitized_text(value: object, sensitive_values: tuple[str, ...]) -> Optional[str]:
    if value is None:
        return None
    return str(sanitize(str(value), sensitive_values))


def _encode_cursor(submitted_at: str, audit_id: str) -> str:
    payload = json.dumps(
        {"submitted_at": submitted_at, "audit_id": audit_id},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = base64.b64decode(
            (cursor + padding).encode(), altchars=b"-_", validate=True
        )
        value = json.loads(payload)
        submitted_at = value["submitted_at"]
        audit_id = value["audit_id"]
        if (
            not isinstance(submitted_at, str)
            or not isinstance(audit_id, str)
            or set(value) != {"submitted_at", "audit_id"}
        ):
            raise ValueError
        return submitted_at, audit_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("invalid audit cursor") from error


class AuditStore:
    def __init__(self, database: Database):
        self.database = database

    def create_pending(
        self,
        request: object,
        actor: str,
        idempotency_key: str,
        region: str,
        sensitive_values: tuple[str, ...],
    ) -> str:
        request_dict = _as_dict(request)
        sanitized_request = sanitize(request_dict, sensitive_values)
        if not isinstance(sanitized_request, dict):
            raise TypeError("audit request must serialize to an object")

        audit_id = str(uuid.uuid4())
        submitted_at = _utc_now().isoformat()
        values = (
            audit_id,
            str(sanitized_request["incident_id"]),
            idempotency_key,
            _sanitized_text(actor, sensitive_values),
            sanitized_request["priority"],
            _sanitized_text(sanitized_request.get("incident_type"), sensitive_values),
            _sanitized_text(sanitized_request.get("location"), sensitive_values),
            _sanitized_text(sanitized_request.get("operator_name"), sensitive_values),
            submitted_at,
            region,
            serialize_sanitized(request_dict, sensitive_values),
            "pending",
        )
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO dispatch_audit (
                   audit_id, incident_id, idempotency_key, actor, priority,
                   incident_type, location, operator_name, submitted_at, region,
                   request_json, outcome
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            connection.commit()
            return audit_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete(
        self,
        audit_id: str,
        result: object,
        duration_ms: int,
        sensitive_values: tuple[str, ...],
    ) -> None:
        result_dict = _as_dict(result)
        outcome = result_dict.get("outcome")
        if outcome not in AUDIT_OUTCOMES - {"pending"}:
            raise ValueError("completed audit outcome is invalid")
        response = result_dict.get("body", result_dict)
        error_category = _sanitized_text(
            result_dict.get("error_category"), sensitive_values
        )

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE dispatch_audit
                   SET completed_at=?, duration_ms=?, http_status=?, response_json=?,
                       outcome=?, error_category=?
                   WHERE audit_id=?""",
                (
                    _utc_now().isoformat(),
                    duration_ms,
                    result_dict.get("http_status"),
                    serialize_sanitized(response, sensitive_values),
                    outcome,
                    error_category,
                    audit_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown audit id: {audit_id}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list(
        self,
        query: Optional[str] = None,
        priority: Optional[int] = None,
        outcome: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if priority is not None and not 1 <= priority <= 5:
            raise ValueError("priority must be between 1 and 5")
        if outcome is not None and outcome not in FILTERABLE_OUTCOMES:
            raise ValueError("invalid audit outcome")

        clauses: list[str] = []
        parameters: list[object] = []
        if query and query.strip():
            escaped = (
                query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            clauses.append(
                """(incident_id LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR incident_type LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR location LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR operator_name LIKE ? ESCAPE '\\' COLLATE NOCASE)"""
            )
            parameters.extend([pattern] * 4)
        if priority is not None:
            clauses.append("priority=?")
            parameters.append(priority)
        if outcome is not None:
            clauses.append("outcome=?")
            parameters.append(outcome)
        if cursor is not None:
            submitted_at, audit_id = _decode_cursor(cursor)
            clauses.append("(submitted_at<? OR (submitted_at=? AND audit_id<?))")
            parameters.extend((submitted_at, submitted_at, audit_id))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit + 1)
        connection = self.database.connect()
        try:
            rows = connection.execute(
                f"""SELECT * FROM dispatch_audit {where}
                    ORDER BY submitted_at DESC, audit_id DESC LIMIT ?""",
                parameters,
            ).fetchall()
        finally:
            connection.close()

        has_more = len(rows) > limit
        selected = rows[:limit]
        items = []
        for row in selected:
            item = dict(row)
            item["request"] = json.loads(item.pop("request_json"))
            response_json = item.pop("response_json")
            item["response"] = (
                json.loads(response_json) if response_json is not None else None
            )
            items.append(item)
        next_cursor = None
        if has_more and selected:
            next_cursor = _encode_cursor(
                selected[-1]["submitted_at"], selected[-1]["audit_id"]
            )
        return {"items": items, "next_cursor": next_cursor}

    def cleanup(self, retention_days: int) -> int:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        cutoff = (_utc_now() - timedelta(days=retention_days)).isoformat()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM dispatch_audit WHERE submitted_at<?", (cutoff,)
            )
            connection.commit()
            return cursor.rowcount
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
