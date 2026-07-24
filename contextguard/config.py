"""Server-side settings. Secrets never leave the process."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    datahub_mcp_url: str = Field(default="", alias="DATAHUB_MCP_URL")
    datahub_token: str = Field(default="", alias="DATAHUB_TOKEN")
    allow_writeback: bool = Field(default=False, alias="CONTEXTGUARD_ALLOW_WRITEBACK")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="CONTEXTGUARD_GEMINI_MODEL")
    mcp_timeout_seconds: float = Field(default=30.0, alias="CONTEXTGUARD_MCP_TIMEOUT")
    mcp_max_retries: int = Field(default=2, alias="CONTEXTGUARD_MCP_RETRIES")

    def require_datahub(self) -> None:
        missing = [
            name
            for name, value in (
                ("DATAHUB_MCP_URL", self.datahub_mcp_url),
                ("DATAHUB_TOKEN", self.datahub_token),
            )
            if not value.strip()
        ]
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(missing)}")

    def require_runtime(self) -> None:
        self.require_datahub()
        if not self.google_api_key.strip():
            raise ValueError("Missing required settings: GOOGLE_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
