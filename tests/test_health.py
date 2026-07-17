import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.config_store import ConfigStore
from app.main import create_app
from app.settings import Settings


def test_health_reports_mock_mode(tmp_path):
    settings = Settings(data_dir=tmp_path, live_dispatch_enabled=False, dfr_config_key=None)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "mock"}
    assert app.state.database.path == tmp_path / "dfr_trigger.db"
    assert app.state.config_store is None


def test_startup_configures_encrypted_store_when_key_is_present(tmp_path):
    encoded_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings = Settings(data_dir=tmp_path, dfr_config_key=encoded_key)
    app = create_app(settings)

    with TestClient(app):
        assert isinstance(app.state.config_store, ConfigStore)
        assert app.state.config_store.load() is None


def test_live_mode_requires_configuration_key(tmp_path):
    settings = Settings(data_dir=tmp_path, live_dispatch_enabled=True)

    with pytest.raises(RuntimeError, match="live mode release gates failed"):
        with TestClient(create_app(settings)):
            pass
