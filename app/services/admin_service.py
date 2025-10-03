from __future__ import annotations

import secrets
from typing import Optional

from sqlalchemy.orm import Session

from ..core import settings as settings_module
from ..domain.models import ConfigItem

_API_KEY_CONFIG_KEY = "orbit_api_key"


class AdminService:
    """Administrative helpers for UI-controlled configuration."""

    def __init__(self, db: Session):
        self._db = db

    def get_api_key(self) -> Optional[str]:
        """Return the stored admin API key, falling back to env for legacy setups."""
        item = self._db.get(ConfigItem, _API_KEY_CONFIG_KEY)
        if item and item.value:
            return item.value
        return settings_module.settings.orbit_api_key

    def set_api_key(self, api_key: str) -> str:
        """Persist the admin API key in the config table."""
        item = self._db.get(ConfigItem, _API_KEY_CONFIG_KEY)
        if item is None:
            item = ConfigItem(key=_API_KEY_CONFIG_KEY, value=api_key)
            self._db.add(item)
        else:
            item.value = api_key
        self._db.flush()
        return api_key

    def clear_api_key(self) -> None:
        item = self._db.get(ConfigItem, _API_KEY_CONFIG_KEY)
        if item:
            self._db.delete(item)
            self._db.flush()

    def generate_api_key(self) -> str:
        """Create a new API key, persist it, and return the plaintext."""
        key = secrets.token_urlsafe(32)
        self.set_api_key(key)
        return key


__all__ = ["AdminService"]
