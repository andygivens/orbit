"""Skylight provider adapter."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from ..infra.skylight_client import SkylightClient
from .base import ProviderAdapter


class SkylightAdapter(ProviderAdapter):
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        conf = config if isinstance(config, dict) else {}
        base_url = conf.get("base_url") or None
        self.client = SkylightClient(
            email=conf.get("email"),
            password=conf.get("password"),
            base_url=base_url,
        )

        # Apply credential overrides
        api_client = self.client.api_client
        if email := conf.get("email"):
            api_client.email = email
        if password := conf.get("password"):
            api_client.password = password

        frame_manager = self.client.frame_manager
        if frame_name := conf.get("frame_name"):
            frame_manager.frame_name = frame_name
        if category_name := conf.get("category_name"):
            frame_manager.category_name = category_name

    async def initialize(self) -> None:
        await self.client._ensure_authenticated()

    async def list_events(self, start: str, end: str) -> Iterable[Dict[str, Any]]:
        return await self.client.list_events(start, end)

    async def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.client.create_event(payload)

    async def update_event(self, provider_uid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.client.update_event(provider_uid, payload)

    async def delete_event(self, provider_uid: str) -> None:
        await self.client.delete_event(provider_uid)
