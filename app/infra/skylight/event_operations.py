# Event operations for Skylight API
from typing import Any, Dict, List

from ...core.logging import logger


class EventOperations:
    """Handles Skylight event CRUD operations"""

    def __init__(self, api_client, frame_manager):
        self.api_client = api_client
        self.frame_manager = frame_manager
        self.logger = logger.bind(component="skylight_events")

    async def list_events(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """List events in date range, filtered by configured category"""
        self.logger.debug("Listing Skylight events", start=start_date, end=end_date,
                         category=self.frame_manager.category_name)

        await self.api_client.ensure_authenticated()
        await self.frame_manager.ensure_frame_and_category()

        # Use the correct query parameters from the working example
        endpoint = (f"/api/frames/{self.frame_manager.frame_id}/calendar_events"
                   f"?date_min={start_date}&date_max={end_date}"
                   f"&timezone=America/New_York"
                   f"&include=categories,calendar_account,event_notification_setting")

        response = await self.api_client.make_request("GET", endpoint)

        data = response.json()
        all_events = data.get("data", []) if isinstance(data, dict) else data

        # Filter events to only include those with our configured category
        filtered_events = []
        for event in all_events:
            relationships = event.get("relationships", {})
            categories_rel = relationships.get("categories", {})
            event_categories = categories_rel.get("data", [])
            event_category_ids = [str(cat.get("id")) for cat in event_categories]

            # Only include events that have our configured category
            category_id = self.frame_manager.category_id
            if category_id and str(category_id) in event_category_ids:
                filtered_events.append(event)

        self.logger.info("Retrieved Skylight events",
                        total_events=len(all_events),
                        filtered_events=len(filtered_events),
                        category=self.frame_manager.category_name,
                        category_id=self.frame_manager.category_id)
        return filtered_events

    async def list_events_dt(self, start, end) -> List[Dict[str, Any]]:
        """Convenience wrapper: accepts datetime objects and delegates to list_events"""
        return await self.list_events(start.isoformat(), end.isoformat())

    async def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new event"""
        await self.api_client.ensure_authenticated()
        await self.frame_manager.ensure_frame_and_category()

        # Ensure defaults for required fields
        if (not event_data.get("category_ids")) and self.frame_manager.category_id:
            event_data = {
                **event_data,
                "category_ids": [self.frame_manager.category_id],
            }
        if not event_data.get("timezone"):
            event_data = {**event_data, "timezone": "America/New_York"}

        self.logger.debug(
            "Creating Skylight event",
            title=event_data.get("summary"),
            category_ids=event_data.get("category_ids"),
            timezone=event_data.get("timezone"),
        )

        endpoint = f"/api/frames/{self.frame_manager.frame_id}/calendar_events"
        response = await self.api_client.make_request("POST", endpoint, json=event_data)

        created_event = response.json()

        # Debug the response to understand the format
        self.logger.debug(
            "Skylight create event response",
            response_data=created_event,
        )

        event_id = created_event.get("id") or created_event.get("data", {}).get("id")
        if not event_id:
            self.logger.warning(
                "No event ID returned from Skylight creation",
                response=created_event,
            )
            # Try to extract from other possible fields
            event_id = created_event.get("event_id")
            if not event_id:
                event_id = str(created_event.get("id", "unknown"))

        self.logger.info(
            "Created Skylight event",
            component="skylight",
            event_id=event_id,
            title=event_data.get("summary", "No title"),
            starts_at=event_data.get("starts_at"),
            ends_at=event_data.get("ends_at"),
            location=event_data.get("location", ""),
            category_ids=event_data.get("category_ids", []),
        )

        return created_event

    async def update_event(
        self,
        event_id: str,
        event_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update an existing event"""
        if not event_id or event_id == "None" or event_id.startswith("temp_"):
            self.logger.warning(
                "Cannot update event with invalid ID",
                event_id=event_id,
            )
            raise ValueError(f"Invalid event ID: {event_id}")

        await self.api_client.ensure_authenticated()
        await self.frame_manager.ensure_frame_and_category()

        # Ensure we never clear the configured category on update
        event_payload = dict(event_data or {})
        category_ids = event_payload.get("category_ids")
        if not category_ids and self.frame_manager.category_id:
            event_payload["category_ids"] = [self.frame_manager.category_id]

        endpoint = (
            f"/api/frames/{self.frame_manager.frame_id}/"
            f"calendar_events/{event_id}"
        )
        response = await self.api_client.make_request("PUT", endpoint, json=event_payload)

        event = response.json()
        self.logger.info("Updated Skylight event", event_id=event_id)
        return event

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event"""
        if not event_id or event_id == "None" or event_id.startswith("temp_"):
            self.logger.warning(
                "Cannot delete event with invalid ID",
                event_id=event_id,
            )
            return False

        try:
            await self.api_client.ensure_authenticated()
            await self.frame_manager.ensure_frame_and_category()

            endpoint = (
                f"/api/frames/{self.frame_manager.frame_id}/"
                f"calendar_events/{event_id}"
            )
            await self.api_client.make_request("DELETE", endpoint)
            return True
        except Exception as e:
            self.logger.error(
                "Failed to delete Skylight event",
                event_id=event_id,
                error=str(e),
            )
            return False

    # Legacy compatibility method
    async def get_events(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Legacy method for backward compatibility"""
        if not start_date or not end_date:
            # Default to a reasonable range if not provided
            from datetime import datetime, timedelta
            start = datetime.now()
            end = start + timedelta(days=30)
            start_date = start.isoformat()
            end_date = end.isoformat()

        return await self.list_events(start_date, end_date)
