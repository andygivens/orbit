from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional


# Data Models
@dataclass(frozen=True)
class TimeRange:
    start_at: str  # RFC3339 UTC
    end_at: str    # RFC3339 UTC

@dataclass(frozen=True)
class ProviderEvent:
    provider_event_id: str
    title: str
    start_at: str
    end_at: str
    location: Optional[str] = None
    notes: Optional[str] = None
    etag: Optional[str] = None

@dataclass(frozen=True)
class EventCreate:
    title: str
    start_at: str
    end_at: str
    location: Optional[str] = None
    notes: Optional[str] = None

@dataclass(frozen=True)
class EventPatch:
    title: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None

@dataclass(frozen=True)
class Page:
    items: List[ProviderEvent]
    next_cursor: Optional[str]

Capability = Literal[
    "read_events",
    "create_events",
    "update_events",
    "delete_events",
    "incremental_sync",
    "webhooks"
]

class ProviderAdapter(ABC):
    type_id: str
    version: str = "0.1.0"

    # Schema & Capabilities
    @abstractmethod
    def config_schema(self) -> Dict[str, Any]:
        """Return JSON Schema for provider configuration."""

    @abstractmethod
    def capabilities(self) -> Iterable[Capability]:
        """Return iterable of capability strings."""

    # Health
    @abstractmethod
    def health(self, ctx, config: Dict[str, Any]) -> Dict[str, Any]:
        """Lightweight probe; returns status dict."""

    # Event Retrieval
    @abstractmethod
    def list_events(self, ctx, config: Dict[str, Any], time_range: TimeRange, cursor: Optional[str], limit: int) -> Page:
        ...

    # Mutations (optional based on capabilities)
    def create_event(self, ctx, config: Dict[str, Any], event: EventCreate) -> ProviderEvent:
        raise NotImplementedError()

    def get_event(self, ctx, config: Dict[str, Any], provider_event_id: str) -> ProviderEvent:
        raise NotImplementedError()

    def patch_event(self, ctx, config: Dict[str, Any], provider_event_id: str, patch: EventPatch, if_match: Optional[str] = None) -> ProviderEvent:
        raise NotImplementedError()

    def delete_event(self, ctx, config: Dict[str, Any], provider_event_id: str) -> None:
        raise NotImplementedError()

    # Webhooks (optional)
    def webhook_subscribe(self, ctx, config: Dict[str, Any]) -> Optional[str]:
        return None

    def webhook_handle(self, ctx, config: Dict[str, Any], raw_payload: bytes) -> List[ProviderEvent]:
        return []
