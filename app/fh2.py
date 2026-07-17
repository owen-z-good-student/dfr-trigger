import httpx
import json

from app.schemas import DispatchRequest, FH2Response, StoredFH2Config


FH2_BASE_URLS = {
    "global": "https://es-flight-api-us.djigate.com",
    "eu": "https://es-flight-api-eu.djigate.com",
}
WORKFLOW_PATH = "/openapi/v0.1/workflow"
MAX_NON_JSON_RESPONSE_BYTES = 4_096
MAX_RESPONSE_BYTES = 65_536
TRUNCATION_MARKER = "\n[TRUNCATED]"


def _description_line(label: str, value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return f"{label}: {value}"


def build_fh2_payload(
    request: DispatchRequest, config: StoredFH2Config
) -> dict:
    incident_type = (
        request.custom_incident_type
        if request.incident_type == "Other"
        else request.incident_type
    )
    optional_lines = (
        _description_line("Incident Type", incident_type),
        _description_line("Location", request.location),
        _description_line("Operator", request.operator_name),
        _description_line("Caller", request.caller_phone),
        _description_line("Description", request.description),
    )
    lines = [line for line in optional_lines if line is not None]
    lines.append(f"Incident ID: {request.incident_id}")

    params = {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "level": request.priority,
        "desc": "\n".join(lines),
    }
    if config.creator_id:
        params["creator"] = config.creator_id

    return {
        "workflow_uuid": config.workflow_uuid,
        "trigger_type": 0,
        "name": f"Emergency Alert - [{request.incident_id}]",
        "params": params,
    }


def _response_body(content: bytes, truncated: bool) -> object | None:
    if truncated:
        return content.decode("utf-8", errors="replace") + TRUNCATION_MARKER
    try:
        return json.loads(content)
    except (ValueError, UnicodeDecodeError):
        text = content[:MAX_NON_JSON_RESPONSE_BYTES].decode(
            "utf-8", errors="replace"
        )
        if len(content) > MAX_NON_JSON_RESPONSE_BYTES:
            text += TRUNCATION_MARKER
        return text


class FH2Client:
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds

    async def send(
        self, config: StoredFH2Config, payload: dict
    ) -> FH2Response:
        url = f"{FH2_BASE_URLS[config.region]}{WORKFLOW_PATH}"
        headers = {
            "Content-Type": "application/json",
            "X-User-Token": config.user_token,
            "x-project-uuid": config.project_uuid,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    content = bytearray()
                    truncated = False
                    response_limit = (
                        MAX_RESPONSE_BYTES
                        if "application/json"
                        in response.headers.get("content-type", "").lower()
                        else MAX_NON_JSON_RESPONSE_BYTES
                    )
                    async for chunk in response.aiter_bytes():
                        remaining = response_limit - len(content)
                        if len(chunk) > remaining:
                            marker_size = len(TRUNCATION_MARKER.encode())
                            content.extend(chunk[: max(0, remaining - marker_size)])
                            truncated = True
                            break
                        content.extend(chunk)
        except (httpx.ReadTimeout, httpx.WriteTimeout):
            return FH2Response(
                outcome="indeterminate", error_category="timeout"
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return FH2Response(outcome="failure", error_category="connection")

        return FH2Response(
            outcome="success" if response.status_code == 200 else "failure",
            http_status=response.status_code,
            body=_response_body(bytes(content), truncated),
            error_category=None if response.status_code == 200 else "http",
        )
