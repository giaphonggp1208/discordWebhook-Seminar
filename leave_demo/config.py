from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8-sig", extra="ignore", case_sensitive=False,
        populate_by_name=True, frozen=True, hide_input_in_errors=True,
    )
    app_version: str = "demo-v1"
    discord_application_id: str = ""
    discord_public_key: str = ""
    discord_guild_id: str = ""
    discord_approval_channel_id: str = ""
    discord_manager_id: str = ""
    discord_bot_token: str = Field(default="", repr=False)
    discord_webhook_deployments: str = Field(default="", repr=False)
    discord_webhook_alerts: str = Field(default="", repr=False)
    discord_webhook_activity: str = Field(default="", repr=False)
    discord_api_base: str = "https://discord.com/api/v10"
    database_url: str = ""
    database_path: Path = PROJECT_ROOT / "data" / "leave-demo.db"
    worker_enabled: bool = Field(default=True, validation_alias="DELIVERY_WORKER_ENABLED")

    @model_validator(mode="after")
    def resolve_database(self) -> "Settings":
        url = self.database_url.strip()
        if not url:
            database = self.database_path
            if not database.is_absolute():
                database = PROJECT_ROOT / database
            url = f"sqlite:///{database.as_posix()}"
        object.__setattr__(self, "database_url", url)
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        # Tests can disable dotenv with LEAVE_ENV_FILE="" or supply a temporary file.
        dotenv = os.getenv("LEAVE_ENV_FILE", str(PROJECT_ROOT / ".env"))
        return cls(_env_file=dotenv or None)

    @property
    def discord_configured(self) -> bool:
        return all(
            (
                self.discord_application_id,
                self.discord_public_key,
                self.discord_guild_id,
                self.discord_approval_channel_id,
                self.discord_manager_id,
            )
        )
