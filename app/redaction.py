import json
import re


SECRET_KEY_SEGMENTS = {
    "auth",
    "authentication",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
SECRET_KEY_SEQUENCES = {("aes", "key"), ("config", "key"), ("encryption", "key")}
MASKED_SUFFIX_FIELDS = {"project_uuid", "workflow_uuid", "creator_id", "creator"}


def _mask_suffix(value: object) -> str:
    text = str(value)
    visible = min(6, len(text))
    return "*" * (len(text) - visible) + text[-visible:]


def _redact_sensitive_values(value: str, sensitive_values: tuple[str, ...]) -> str:
    cleaned = value
    for sensitive in sorted(set(sensitive_values), key=len, reverse=True):
        if sensitive:
            cleaned = cleaned.replace(sensitive, "[REDACTED_VALUE]")
    return cleaned


def _key_segments(key: object) -> tuple[str, ...]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    return tuple(part for part in re.sub(r"[^a-zA-Z0-9]+", "_", text).lower().split("_") if part)


def _is_secret_key(key: object) -> bool:
    segments = _key_segments(key)
    if any(segment in SECRET_KEY_SEGMENTS for segment in segments):
        return True
    return any(
        segments[index : index + len(sequence)] == sequence
        for sequence in SECRET_KEY_SEQUENCES
        for index in range(len(segments) - len(sequence) + 1)
    )


def sanitize(value: object, sensitive_values: tuple[str, ...] = ()) -> object:
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            key_text = str(key)
            sanitized_key = _redact_sensitive_values(key_text, sensitive_values)
            output_key = sanitized_key if sanitized_key != key_text else key
            normalized = "_".join(_key_segments(key))
            if _is_secret_key(key):
                cleaned[output_key] = "[REDACTED]"
            elif normalized in MASKED_SUFFIX_FIELDS:
                sanitized_child = sanitize(child, sensitive_values)
                cleaned[output_key] = (
                    sanitized_child
                    if sanitized_child != child
                    else _mask_suffix(child)
                )
            else:
                cleaned[output_key] = sanitize(child, sensitive_values)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize(item, sensitive_values) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_values(value, sensitive_values)
    return value


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()


def serialize_sanitized(
    value: object,
    sensitive_values: tuple[str, ...] = (),
    max_bytes: int = 65_536,
) -> str:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    encoded = _json_bytes(sanitize(value, sensitive_values))
    if len(encoded) <= max_bytes:
        return encoded.decode("ascii")

    def truncated(preview_length: int) -> bytes:
        return _json_bytes(
            {
                "truncated": True,
                "original_bytes": len(encoded),
                "preview": encoded[:preview_length].decode("ascii"),
            }
        )

    if len(truncated(0)) > max_bytes:
        raise ValueError("max_bytes is too small for truncation metadata")

    low = 0
    high = min(len(encoded), max_bytes)
    while low < high:
        middle = (low + high + 1) // 2
        if len(truncated(middle)) <= max_bytes:
            low = middle
        else:
            high = middle - 1
    return truncated(low).decode("ascii")
