# Core settings and configuration

from typing import ClassVar, Dict, List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    NOTE: Provider credential env variables removed; credentials now live in
    DB provider configs.
    Deprecated envs (ignored if present):
      ICLOUD_USERNAME, ICLOUD_APP_PASSWORD, ICLOUD_CALENDAR_NAME,
      SKYLIGHT_EMAIL, SKYLIGHT_PASSWORD, SKYLIGHT_FRAME_NAME, SKYLIGHT_CATEGORY_NAME,
      ORBIT_BOOTSTRAP_DEFAULT_PROVIDERS
    """

    # API / Auth
    orbit_api_key: Optional[str] = Field(
        None, description="API key required for privileged internal auth"
    )

    # Sync defaults (used as fallback only; can move to DB later)
    poll_interval_sec: int = Field(
        180, description="Default interval (seconds) between scheduled sync runs"
    )
    sync_window_days_past: int = Field(
        30, description="Historical window (days) to include when syncing events"
    )
    sync_window_days_future: int = Field(
        90, description="Future window (days) to include when syncing events"
    )

    # Database
    database_url: str = Field(
        "sqlite:///./orbit.db", description="SQLAlchemy database URL"
    )

    # Logging
    log_level: str = Field("INFO", description="Root log level")

    # Internal list of deprecated env names for audit logging
    _deprecated_env_vars: List[str] = [
        "ICLOUD_USERNAME",
        "ICLOUD_APP_PASSWORD",
        "ICLOUD_CALENDAR_NAME",
        "SKYLIGHT_EMAIL",
        "SKYLIGHT_PASSWORD",
        "SKYLIGHT_FRAME_NAME",
        "SKYLIGHT_CATEGORY_NAME",
        "ORBIT_BOOTSTRAP_DEFAULT_PROVIDERS",
        "ORBIT_API_KEY",
    ]

    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",  # manual mapping for legacy names
        extra="ignore",
    )

    # Environment variable name overrides (backwards compat). Pydantic v2 reads env var
    # precedence by field name -> env_prefix + field name. We still silently accept
    # legacy explicit names by manually patching after init if present.
    _legacy_env_map: ClassVar[Dict[str, str]] = {
        "orbit_api_key": "ORBIT_API_KEY",
        "poll_interval_sec": "POLL_INTERVAL_SEC",
        "sync_window_days_past": "SYNC_WINDOW_DAYS_PAST",
        "sync_window_days_future": "SYNC_WINDOW_DAYS_FUTURE",
        "database_url": "DATABASE_URL",
        "log_level": "LOG_LEVEL",
    }

    def __init__(self, **data):  # type: ignore[override]
        import os
        # Access class dict directly to avoid pydantic attribute machinery during init
        legacy_map = type(self)._legacy_env_map
        for field, legacy_name in legacy_map.items():
            if legacy_name in os.environ and field not in data:
                data[field] = os.environ[legacy_name]
        super().__init__(**data)


# Global settings instance
settings = Settings()
