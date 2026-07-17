import pytest
import inspect
import base64
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def _key() -> str:
    return base64.urlsafe_b64encode(b"r" * 32).decode()


def _failing_live_settings(tmp_path, **overrides):
    base = dict(
        data_dir=tmp_path,
        live_dispatch_enabled=True,
        fh2_contract_verified=False,
        dfr_config_key=None,
        csrf_secret="mock-only-change-before-live",
        trusted_identity_header=None,
        trusted_proxy_cidrs="",
        public_origin="http://example.com",
    )
    base.update(overrides)
    return Settings(**base)


def test_live_mode_startup_fails_with_all_missing_gates(tmp_path):
    app = create_app(_failing_live_settings(tmp_path))
    with pytest.raises(RuntimeError) as exc_info:
        with TestClient(app):
            pass
    assert "live mode release gates failed" in str(exc_info.value)


def test_live_mode_startup_fails_listing_each_missing_gate(tmp_path):
    app = create_app(_failing_live_settings(tmp_path))
    with pytest.raises(RuntimeError) as exc_info:
        with TestClient(app):
            pass
    message = str(exc_info.value)
    assert "fh2_contract_verified" in message
    assert "dfr_config_key" in message
    assert "trusted_identity_header" in message
    assert "trusted_proxy_cidrs" in message


def test_mock_mode_starts_without_production_secrets(tmp_path):
    settings = Settings(data_dir=tmp_path, live_dispatch_enabled=False)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"


def test_create_app_has_no_release_gate_bypass():
    assert "_check_gates" not in inspect.signature(create_app).parameters


def test_live_mode_rejects_short_csrf_secret(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        live_dispatch_enabled=True,
        fh2_contract_verified=True,
        dfr_config_key=_key(),
        csrf_secret="short",
        public_origin="https://app.example",
        trusted_identity_header="x-member-id",
        trusted_proxy_cidrs="10.0.0.1/32",
    )
    with pytest.raises(RuntimeError, match="live mode release gates failed"):
        with TestClient(create_app(settings)):
            pass


def test_live_mode_protects_html_and_static_assets_from_untrusted_origin(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        live_dispatch_enabled=True,
        fh2_contract_verified=True,
        dfr_config_key=_key(),
        csrf_secret="c" * 32,
        public_origin="https://app.example",
        trusted_identity_header="x-member-id",
        trusted_proxy_cidrs="10.0.0.1/32",
    )
    with TestClient(
        create_app(settings),
        base_url="https://app.example",
        client=("203.0.113.10", 50000),
    ) as client:
        assert client.get("/").status_code == 403
        assert client.get("/static/styles.css").status_code == 403


def test_html_uses_local_vendor_assets_and_document_csp(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "unpkg.com" not in response.text
    assert "/static/vendor/leaflet/leaflet.js" in response.text
    assert "/static/vendor/lucide/lucide.js" in response.text
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "img-src 'self' https://tile.openstreetmap.org data:" in csp
