from adapters.minimal.adapter import MinimalProvider
from app.sdk import ProviderContext


def test_minimal_adapter_smoke():
    adapter = MinimalProvider()
    schema = adapter.config_schema()
    assert schema["type"] == "object"
    assert "api_key" in schema["properties"]
    assert set(adapter.capabilities()) == {"read_events"}

    ctx = ProviderContext()
    health = adapter.health(ctx, {"api_key": "dummy"})
    assert health["status"] == "ok"

    # List events first page
    from app.sdk import TimeRange
    tr = TimeRange(start_at="2024-01-01T00:00:00Z", end_at="2024-01-01T12:00:00Z")
    page1 = adapter.list_events(ctx, {"api_key": "dummy"}, tr, cursor=None, limit=10)
    assert len(page1.items) <= 10
    if page1.next_cursor:
        page2 = adapter.list_events(ctx, {"api_key": "dummy"}, tr, cursor=page1.next_cursor, limit=10)
        # Second page returns no duplicate items
        ids1 = {e.provider_event_id for e in page1.items}
        ids2 = {e.provider_event_id for e in page2.items}
        assert ids1.isdisjoint(ids2)
