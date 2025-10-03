"""Base classes and interfaces for provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Optional


class ProviderAdapter(ABC):
    """Abstract adapter every provider implementation must follow."""

    def __init__(self, provider_id: str, config: Dict[str, Any]):
        self.provider_id = provider_id
        self.config = config

    @abstractmethod
    async def initialize(self) -> None:
        """Establish any remote connections and perform validation."""

    @abstractmethod
    async def list_events(self, start: str, end: str) -> Iterable[Dict[str, Any]]:
        """Return provider-native events for the time range."""

    @abstractmethod
    async def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create an event and return provider response."""

    @abstractmethod
    async def update_event(self, provider_uid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update an event by provider UID."""

    @abstractmethod
    async def delete_event(self, provider_uid: str) -> None:
        """Delete an event by provider UID."""

    async def close(self) -> None:
        """Optional teardown hook."""

    @property
    def timezone(self) -> Optional[str]:
        return self.config.get("timezone")
