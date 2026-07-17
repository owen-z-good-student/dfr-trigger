import base64
import os

import pytest
import stat

from app.config_store import ConfigStore
from app.crypto import ValueCipher
from app.db import Database
from app.schemas import ConfigWrite


def key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_configuration_round_trip_masks_identifiers(tmp_path):
    database = Database(tmp_path / "dfr.db")
    database.initialize()
    store = ConfigStore(database, ValueCipher(key()))
    saved = store.save(
        ConfigWrite(
            region="eu",
            user_token="token-secret",
            project_uuid="bfff3bbe-ecc4-44f4-ae94-9057b69a6a9a",
            workflow_uuid="ccfcb747-87dd-4caa-94e2-c08b5e164dd3",
            creator_id="1988423428261173248",
        ),
        actor="irving.zhang",
    )
    assert saved.token_configured is True
    assert saved.project_uuid_suffix == "9a6a9a"
    assert saved.workflow_uuid_suffix == "164dd3"
    assert saved.creator_id_suffix == "173248"
    assert store.load().user_token == "token-secret"


def test_wrong_key_fails_closed(tmp_path):
    database = Database(tmp_path / "dfr.db")
    database.initialize()
    ConfigStore(database, ValueCipher(key())).save(
        ConfigWrite(
            region="global",
            user_token="secret-1",
            project_uuid="project-123456",
            workflow_uuid="workflow-123456",
            creator_id="creator-123456",
        ),
        actor="tester",
    )
    with pytest.raises(ValueError, match="configuration decryption failed"):
        ConfigStore(database, ValueCipher(key())).load()


def test_database_uses_restrictive_runtime_permissions(tmp_path):
    database = Database(tmp_path / "private" / "dfr.db")
    database.initialize()
    assert stat.S_IMODE(database.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.path.stat().st_mode) == 0o600
