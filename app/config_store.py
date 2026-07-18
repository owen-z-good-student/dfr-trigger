from datetime import datetime, timezone
from typing import Optional

from app.crypto import ValueCipher
from app.db import Database
from app.schemas import ConfigStatus, ConfigWrite, StoredFH2Config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def suffix(value: str) -> str:
    return value[-6:]


class ConfigStore:
    def __init__(self, database: Database, cipher: ValueCipher):
        self.database = database
        self.cipher = cipher

    def save(self, value: ConfigWrite, actor: str) -> ConfigStatus:
        now = utc_now()
        encrypted = [
            self.cipher.encrypt(value.user_token),
            self.cipher.encrypt(value.project_uuid),
            self.cipher.encrypt(value.workflow_uuid),
            self.cipher.encrypt(value.creator_id) if value.creator_id else None,
        ]
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO fh2_config VALUES (1,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET region=excluded.region,
                user_token=excluded.user_token, project_uuid=excluded.project_uuid,
                workflow_uuid=excluded.workflow_uuid, creator_id=excluded.creator_id,
                updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
                (value.region, *encrypted, now, now, actor),
            )
            connection.commit()
        return self.status()

    def load(self) -> Optional[StoredFH2Config]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM fh2_config WHERE id=1"
            ).fetchone()
        if row is None:
            return None
        return StoredFH2Config(
            region=row["region"],
            user_token=self.cipher.decrypt(row["user_token"]),
            project_uuid=self.cipher.decrypt(row["project_uuid"]),
            workflow_uuid=self.cipher.decrypt(row["workflow_uuid"]),
            creator_id=self.cipher.decrypt(row["creator_id"]) if row["creator_id"] else None,
        )

    def status(self) -> ConfigStatus:
        value = self.load()
        if value is None:
            return ConfigStatus()
        return ConfigStatus(
            region=value.region,
            token_configured=True,
            project_uuid_suffix=suffix(value.project_uuid),
            workflow_uuid_suffix=suffix(value.workflow_uuid),
            creator_id_suffix=suffix(value.creator_id) if value.creator_id else None,
        )
