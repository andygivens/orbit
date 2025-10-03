"""
Event handlers for MCP (Model Context Protocol) integration.

This module handles all event-related MCP tool calls:
- create_event: Create new events in both Apple and Skylight
- list_events: List events by period (today, week, month)
- update_event: Update existing events across providers
- delete_event: Delete events from both providers
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ...core.logging import logger
from ...domain.models import serialize_datetime
from ...infra.db import get_db_session
from ...services.provider_event_service import (
    EventNotFoundError,
    ProviderEventService,
    ProviderEventServiceError,
)


async def handle_create_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle create_event tool call"""
    try:
        if "title" not in args:
            return {"error": "title is required"}
        start_key = "start_at" if "start_at" in args else "start"
        if start_key not in args:
            return {"error": "start time is required"}

        start_dt = _parse_datetime(args[start_key])
        if not start_dt:
            return {"error": f"Invalid start time format: {args[start_key]}"}

        end_key = "end_at" if "end_at" in args else "end"
        end_value = args.get(end_key)
        end_dt = _parse_datetime(end_value) if end_value else None
        if end_value and not end_dt:
            return {"error": f"Invalid end time format: {end_value}"}
        if not end_dt:
            end_dt = start_dt + timedelta(hours=1)

        categories = list(
            args.get("categories", [])
            or ([] if not args.get("category") else [args["category"]])
        )

        notes = args.get("notes", "")
        attendees = args.get("attendees", [])
        if attendees:
            attendee_text = f"Attendees: {', '.join(attendees)}"
            notes = f"{attendee_text}\n{notes}".strip()
        if categories:
            category_text = f"Categories: {', '.join(categories)}"
            notes = f"{category_text}\n{notes}".strip()

        event_service = ProviderEventService()
        result = await event_service.create_event(
            {
                "title": args["title"],
                "start": start_dt,
                "end": end_dt,
                "location": args.get("location", ""),
                "notes": notes,
            },
            category_names=categories or None,
        )

        return {
            "success": True,
            "message": f"Created event '{result.get('title', args['title'])}'"
            + (f" in categories: {', '.join(categories)}" if categories else ""),
            "event": {
                "id": result.get("id"),
                "title": result.get("title"),
                "start_at": result.get("start_at"),
                "end_at": result.get("end_at"),
                "categories": categories,
                "providers": result.get("providers", []),
            },
        }

    except ProviderEventServiceError as exc:
        logger.error("Failed to create event via MCP", error=str(exc))
        return {"error": f"Failed to create event: {str(exc)}"}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to create event via MCP", error=str(exc))
        return {"error": f"Failed to create event: {str(exc)}"}


async def handle_list_events(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle list_events tool call"""
    try:
        period = args.get("period", "today")

        # Calculate date range based on period
        now = datetime.now()

        if period == "today":
            start_of_period = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_period = start_of_period + timedelta(days=1)
        elif period == "week":
            # Start of current week (Monday)
            days_since_monday = now.weekday()
            start_of_period = (
                now - timedelta(days=days_since_monday)
            ).replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_period = start_of_period + timedelta(days=7)
        elif period == "month":
            # Start of current month
            start_of_period = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            # Start of next month
            if now.month == 12:
                end_of_period = start_of_period.replace(year=now.year + 1, month=1)
            else:
                end_of_period = start_of_period.replace(month=now.month + 1)
        else:
            # Default to today
            start_of_period = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_period = start_of_period + timedelta(days=1)

        with get_db_session() as db:
            from ...domain.models import Event
            # Query events in the period
            events = db.query(Event).filter(
                Event.start_at >= start_of_period,
                Event.start_at < end_of_period,
                Event.tombstoned.is_(False)
            ).order_by(Event.start_at).all()

            # Convert to dict format
            events_list = []
            for event in events:
                events_list.append({
                    "id": event.id,
                    "title": event.title,
                    "start_at": serialize_datetime(event.start_at),
                    "end_at": serialize_datetime(event.end_at),
                    "location": event.location or "",
                    "notes": event.notes or "",
                    "updated_at": (
                        serialize_datetime(event.updated_at)
                    )
                })

        return {
            "success": True,
            "period": period,
            "events": events_list,
            "count": len(events_list)
        }

    except Exception as e:
        logger.error("Failed to list events via MCP", error=str(e))
        return {"error": f"Failed to list events: {str(e)}"}


async def handle_update_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle update_event tool call"""
    try:
        event_id = args.get("event_id")
        updates = args.get("updates", {})

        if not event_id:
            return {"error": "event_id is required"}

        if not updates:
            return {"error": "updates are required"}
        event_service = ProviderEventService()
        category_names = updates.get("categories") or []

        try:
            normalized_updates: Dict[str, Any] = {}
            for key, value in updates.items():
                if key in {"start", "start_at"}:
                    normalized_updates["start_at"] = value
                elif key in {"end", "end_at"}:
                    normalized_updates["end_at"] = value
                else:
                    normalized_updates[key] = value
            result = await event_service.update_event(
                event_id,
                normalized_updates,
                category_names=category_names,
            )
        except EventNotFoundError:
            return {"error": f"Event with id {event_id} not found"}
        except ProviderEventServiceError as exc:
            logger.error("Failed to update event via MCP", error=str(exc))
            return {"error": f"Failed to update event: {str(exc)}"}

        return {
            "success": True,
            "message": f"Updated event '{result.get('title', event_id)}'",
            "event": {
                "id": result.get("id", event_id),
                "title": result.get("title"),
                "start_at": result.get("start_at"),
                "end_at": result.get("end_at"),
                "location": result.get("location", ""),
                "notes": result.get("notes", ""),
                "providers": result.get("providers", []),
            },
        }

    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to update event via MCP", error=str(exc))
        return {"error": f"Failed to update event: {str(exc)}"}


async def handle_delete_event(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle delete_event tool call"""
    try:
        event_id = args.get("event_id")

        if not event_id:
            return {"error": "event_id is required"}
        event_service = ProviderEventService()
        try:
            await event_service.delete_event(event_id)
        except EventNotFoundError:
            return {"error": f"Event with id {event_id} not found"}
        except ProviderEventServiceError as exc:
            logger.error("Failed to delete event via MCP", error=str(exc))
            return {"error": f"Failed to delete event: {str(exc)}"}

        return {
            "success": True,
            "message": f"Deleted event '{event_id}'",
            "event_id": event_id,
        }

    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to delete event via MCP", error=str(exc))
        return {"error": f"Failed to delete event: {str(exc)}"}


def _parse_datetime(dt_str: str) -> Optional[datetime]:
    """Parse datetime string with multiple format support"""
    try:
        # Try various formats
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",      # 2025-09-03T19:00:00-04:00
            "%Y-%m-%dT%H:%M:%S",        # 2025-09-03T19:00:00
            "%Y-%m-%d %H:%M:%S",        # 2025-09-03 19:00:00
            "%Y-%m-%d %H:%M",           # 2025-09-03 19:00
            "%Y-%m-%dT%H:%M",           # 2025-09-03T19:00
            "%Y-%m-%d",                 # 2025-09-03
            "%m/%d/%Y %H:%M:%S",        # 9/3/2025 19:00:00
            "%m/%d/%Y %H:%M",           # 9/3/2025 19:00
            "%m/%d/%Y",                 # 9/3/2025
        ]

        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue

        # If no format worked, raise an error
        raise ValueError(f"Could not parse datetime: {dt_str}")

    except Exception as e:
        logger.error("Failed to parse datetime", dt_str=dt_str, error=str(e))
        return None
