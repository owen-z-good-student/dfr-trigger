from functools import lru_cache
from pathlib import Path
from typing import Optional,  Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    data_dir: Path = Field(default=Path("data"), validation_alias="DFR_DATA_DIR")
    live_dispatch_enabled: bool = False
    fh2_contract_verified: bool = False
    dfr_config_key: Optional[str] = None
    csrf_secret: str = "mock-only-change-before-live"
    trusted_identity_header: Optional[str] = None
    trusted_proxy_cidrs: str = ""
    public_origin: str = "http://testserver"
    fh2_timeout_seconds: float = 10.0
    geocoding_timeout_seconds: float = 5.0
    geocodes_per_user_per_minute: int = 10
    geocodes_per_instance_per_minute: int = 30
    log_retention_days: int = 7
    dispatches_per_user_per_minute: int = 5
    dispatches_per_instance_per_minute: int = 20
    dispatches_per_project_per_minute: int = 20
    dispatch_concurrency_per_project: int = 1
    dev_mode: bool = False

    @property
    def mode(self) -> Literal["mock", "live"]:
        return "live" if self.live_dispatch_enabled else "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
