# Conflict resolution logic for sync operations
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from ..core.logging import logger
from ..domain.models import Event


class ConflictResolver:
    def __init__(self):
        self.logger = logger.bind(component="conflicts")

    def resolve_event_conflict(
        self,
        apple_event: Optional[Dict[str, Any]],
        skylight_event: Optional[Dict[str, Any]],
        orbit_event: Optional[Event],
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Resolve conflicts between Apple, Skylight, and existing Orbit events.

        Returns:
            Tuple of (action, winning_event) where action is one of:
            - "create": Create new event
            - "update": Update existing event
            - "delete": Delete event (tombstone)
            - "skip": No action needed
        """

        # Case 1: Event deleted in one provider
        if self._is_deleted(apple_event) and self._is_deleted(skylight_event):
            if orbit_event and not orbit_event.tombstoned:
                self.logger.info(
                    "Event deleted in both providers",
                    orbit_event_id=orbit_event.id,
                )
                return "delete", {}
            return "skip", {}

        # Case 2: Event exists in only one provider
        if apple_event and not skylight_event:
            if orbit_event and orbit_event.tombstoned:
                # Don't resurrect tombstoned events
                return "skip", {}
            return self._resolve_single_provider("apple", apple_event, orbit_event)

        if skylight_event and not apple_event:
            if orbit_event and orbit_event.tombstoned:
                return "skip", {}
            return self._resolve_single_provider(
                "skylight",
                skylight_event,
                orbit_event,
            )

        # Case 3: Event exists in both providers - resolve conflict
        if apple_event and skylight_event:
            return self._resolve_dual_provider_conflict(
                apple_event,
                skylight_event,
                orbit_event,
            )

        # Case 4: Event doesn't exist anywhere
        return "skip", {}

    def _resolve_single_provider(
        self,
        provider: str,
        provider_event: Dict[str, Any],
        orbit_event: Optional[Event],
    ) -> Tuple[str, Dict[str, Any]]:
        """Handle event that exists in only one provider"""

        if not orbit_event:
            self.logger.debug(
                "Creating new event from single provider",
                provider=provider,
            )
            return "create", provider_event

        # Check if update is needed
        if self._needs_update(provider_event, orbit_event):
            self.logger.debug(
                "Updating event from single provider",
                provider=provider,
                orbit_event_id=orbit_event.id,
            )
            return "update", provider_event

        return "skip", {}

    def _resolve_dual_provider_conflict(
        self,
        apple_event: Dict[str, Any],
        skylight_event: Dict[str, Any],
        orbit_event: Optional[Event],
    ) -> Tuple[str, Dict[str, Any]]:
        """Resolve conflict when event exists in both providers"""

        apple_updated = self._get_last_updated(apple_event)
        skylight_updated = self._get_last_updated(skylight_event)

        # Rule 1: Use newest timestamp if significantly different (>1 minute)
        if apple_updated and skylight_updated:
            time_diff = abs((apple_updated - skylight_updated).total_seconds())
            if time_diff > 60:  # More than 1 minute difference
                if apple_updated > skylight_updated:
                    self.logger.debug(
                        "Apple event is newer",
                        apple_time=apple_updated,
                        skylight_time=skylight_updated,
                    )
                    winning_event = apple_event
                else:
                    self.logger.debug(
                        "Skylight event is newer",
                        apple_time=apple_updated,
                        skylight_time=skylight_updated,
                    )
                    winning_event = skylight_event
            else:
                # Rule 2: Timestamps very close - prefer Apple as tiebreaker
                self.logger.debug(
                    "Timestamps close, preferring Apple",
                    apple_time=apple_updated,
                    skylight_time=skylight_updated,
                )
                winning_event = apple_event
        else:
            # Rule 3: Missing timestamp info - prefer Apple
            self.logger.debug("Missing timestamp info, preferring Apple")
            winning_event = apple_event

        if not orbit_event:
            return "create", winning_event

        if self._needs_update(winning_event, orbit_event):
            return "update", winning_event

        return "skip", {}

    def _is_deleted(self, event: Optional[Dict[str, Any]]) -> bool:
        """Check if an event represents a deletion"""
        if not event:
            return True
        return event.get("deleted", False) or event.get("status") == "deleted"

    def _needs_update(self, provider_event: Dict[str, Any], orbit_event: Event) -> bool:
        """Check if orbit event needs to be updated based on provider event"""

        # Compare key fields
        title_changed = provider_event.get("title", "") != orbit_event.title
        start_changed = self._datetime_changed(
            provider_event.get("start_at") or provider_event.get("start"),
            orbit_event.start_at,
        )
        end_changed = self._datetime_changed(
            provider_event.get("end_at") or provider_event.get("end"),
            orbit_event.end_at,
        )
        location_changed = (
            provider_event.get("location", "")
            != (orbit_event.location or "")
        )
        notes_changed = (
            provider_event.get("notes", "")
            != (orbit_event.notes or "")
        )

        return any(
            [
                title_changed,
                start_changed,
                end_changed,
                location_changed,
                notes_changed,
            ]
        )

    def _datetime_changed(self, provider_dt, orbit_dt) -> bool:
        """Compare datetimes with tolerance for minor differences"""
        if not provider_dt or not orbit_dt:
            return provider_dt != orbit_dt

        if isinstance(provider_dt, str):
            try:
                provider_dt = datetime.fromisoformat(provider_dt.replace('Z', '+00:00'))
            except ValueError:
                return True

        # Allow 1 minute tolerance for datetime differences
        time_diff = abs((provider_dt - orbit_dt).total_seconds())
        return time_diff > 60

    def _get_last_updated(self, event: Dict[str, Any]) -> Optional[datetime]:
        """Extract last updated timestamp from provider event"""

        # Try various timestamp fields
        for field in (
            "updated_at",
            "last_updated",
            "modified",
            "last_modified",
            "dtlastmodified",
        ):
            value = event.get(field)
            if value:
                if isinstance(value, datetime):
                    return value
                if isinstance(value, str):
                    try:
                        return datetime.fromisoformat(value.replace('Z', '+00:00'))
                    except ValueError:
                        continue

        # Fallback to start time if no update timestamp
        start_time = event.get("start_at") or event.get("start")
        if start_time and isinstance(start_time, datetime):
            return start_time

        return None
