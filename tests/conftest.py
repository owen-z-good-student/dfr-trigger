import base64
import os
import socket
import threading
import time

import pytest
import uvicorn

from app.config_store import ConfigStore
from app.crypto import ValueCipher
from app.db import Database
from app.main import create_app
from app.schemas import ConfigWrite
from app.settings import Settings


@pytest.fixture
def database(tmp_path):
    value = Database(tmp_path / "dfr.db")
    value.initialize()
    return value


@pytest.fixture
def live_server_url(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    encoded_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings = Settings(
        data_dir=tmp_path,
        live_dispatch_enabled=False,
        dfr_config_key=encoded_key,
        csrf_secret="browser-test-secret",
        public_origin=url,
    )
    database = Database(tmp_path / "dfr_trigger.db")
    database.initialize()
    ConfigStore(database, ValueCipher(encoded_key)).save(
        ConfigWrite(
            region="eu",
            user_token="synthetic-test-token",
            project_uuid="project-123456",
            workflow_uuid="workflow-123456",
            creator_id="creator-123456",
        ),
        actor="browser-test",
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings), host="127.0.0.1", port=port,
            log_level="error", ws="none"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield url
    server.should_exit = True
    thread.join(timeout=5)
