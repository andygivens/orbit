from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable

from app.sdk import Page, ProviderAdapter, ProviderEvent, TimeRange


class MinimalProvider(ProviderAdapter):
    type_id = "minimal"
    version = "1.0.0"

    def config_schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "api_key": {"type": "string"}
            },
            "required": ["api_key"],
            "additionalProperties": False
        }

    def capabilities(self) -> Iterable[str]:
        return ["read_events"]

    def health(self, ctx, config: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "time": datetime.utcnow().isoformat()}

    def list_events(
        self,
        ctx,
        config: Dict[str, Any],
        time_range: TimeRange,
        cursor: str | None,
        limit: int,
    ) -> Page:
        # Single static event in window
        start = datetime.now(timezone.utc)
        end = start + timedelta(hours=1)
        evt = ProviderEvent(
            provider_event_id="evt_1",
            title="Demo Event",
            start_at=start.isoformat(),
            end_at=end.isoformat(),
        )
        items = [evt] if cursor is None else []  # only first page has the item
        next_cursor = "end" if cursor is None else None
        return Page(items=items[:limit], next_cursor=next_cursor)
