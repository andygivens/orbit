"""Regression tests for Orbit infrastructure clients."""

import pytest

from app.infra.caldav_client import AppleCalDAVClient
from app.infra.skylight.api_client import SkylightAPIClient
from app.infra.skylight_client import SkylightClient


def test_apple_caldav_client_allows_explicit_credentials():
    """AppleCalDAVClient should honour explicit credentials for tests/tools."""
    client = AppleCalDAVClient(
        username="test@example.com",
        password="app-password",
        caldav_url="https://caldav.example.com",
    )

    assert client.username == "test@example.com"
    assert client.password == "app-password"
    assert client.caldav_url == "https://caldav.example.com"


def test_skylight_api_client_override_credentials():
    """SkylightAPIClient should accept credential overrides."""
    client = SkylightAPIClient(
        base_url="https://skylight.test",
        email="person@example.com",
        password="secret",
    )

    assert client.base_url == "https://skylight.test"
    assert client.email == "person@example.com"
    assert client.password == "secret"


def test_skylight_client_injects_modules():
    """SkylightClient should propagate injected components."""
    api_client = SkylightAPIClient(base_url="https://skylight.test")
    client = SkylightClient(api_client=api_client)

    assert client.api_client is api_client
    assert client.frame_manager.api_client is api_client
    assert client.event_ops.api_client is api_client


class _DummyCalendar:
    def __init__(self, name: str, display_name: str | None = None):
        self.name = name
        self._display_name = display_name

    def get_properties(self, props):  # pragma: no cover - simple stub
        return {"{DAV:}displayname": self._display_name}


def test_apple_caldav_client_selects_configured_calendar_case_insensitive():
    client = AppleCalDAVClient(calendar_name="  andy  ")
    client.calendars = [
        _DummyCalendar("Family"),
        _DummyCalendar("Andy"),
    ]

    calendar = client.get_primary_calendar()
    assert calendar.name == "Andy"


def test_apple_caldav_client_raises_when_calendar_missing():
    client = AppleCalDAVClient(calendar_name="Sales")
    client.calendars = [
        _DummyCalendar("Family"),
        _DummyCalendar("Andy"),
    ]

    with pytest.raises(ValueError) as exc:
        client.get_primary_calendar()

    assert "Sales" in str(exc.value)
    assert "Family" in str(exc.value)


def test_apple_caldav_client_defaults_when_not_specified():
    client = AppleCalDAVClient()
    client.calendars = [
        _DummyCalendar("Family"),
        _DummyCalendar("Andy"),
    ]

    calendar = client.get_primary_calendar()
    assert calendar.name == "Family"
