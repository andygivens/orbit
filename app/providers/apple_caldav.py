"""Apple CalDAV provider adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Iterable

from ..core.logging import logger
from ..infra.caldav_client import AppleCalDAVClient
from .base import ProviderAdapter

DEFAULT_CALDAV_URL = "https://caldav.icloud.com"


class AppleCalDAVAdapter(ProviderAdapter):
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        caldav_url = config.get("caldav_url")
        if isinstance(caldav_url, str):
            caldav_url = caldav_url.strip() or None

        allow_override = "app_password" not in config
        if not allow_override and caldav_url and caldav_url != DEFAULT_CALDAV_URL:
            logger.info(
                "Ignoring custom CalDAV URL for Apple provider; enforcing default",
                provider_id=provider_id,
            )
            caldav_url = None

        self.client = AppleCalDAVClient(
            username=config.get("username"),
            password=config.get("app_password"),
            caldav_url=caldav_url or DEFAULT_CALDAV_URL,
            calendar_name=config.get("calendar_name"),
        )

    async def initialize(self) -> None:
        await asyncio.to_thread(self.client.connect)

    async def list_events(self, start: str, end: str) -> Iterable[Dict[str, Any]]:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        events = await asyncio.to_thread(self.client.list_events, start_dt, end_dt)
        return events

    async def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(self.client.create_event, payload)

    async def update_event(self, provider_uid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(self.client.update_event, provider_uid, payload)

    async def delete_event(self, provider_uid: str) -> None:
        await asyncio.to_thread(self.client.delete_event, provider_uid)
