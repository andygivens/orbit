"""
Search handlers for MCP (Model Context Protocol) integration.

This module handles search-related MCP tool calls and utilities:
- handle_search: Natural language search across events
- Date/time parsing utilities for search queries
- Period detection (today, tomorrow, week, month)
- Database query helpers for event search
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ...core.logging import logger
from ...domain.models import serialize_datetime
from ...infra.db import get_db_session


async def handle_search(arguments: Dict[str, Any], req_id: int = 1) -> Dict[str, Any]:
    """Handle search tool call with natural language queries"""
    try:
        query = (arguments.get("query") or "").strip()
        if not query:
            return {"error": "Search query is required"}

        logger.info("Search query received",
                   query=query,
                   query_length=len(query))

        results = []

        # Try period detection first (today, week, month, etc.)
        period = detect_period_from_query(query)
        if period:
            now = datetime.now()
            start, end = compute_range_for_period(period, now)
            results = list_events_from_db(start, end)
        else:
            # Try specific date parsing
            date_match = parse_specific_date(query)
            if date_match:
                start = date_match.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
                results = list_events_from_db(start, end)
            else:
                # Try month/year parsing
                my = parse_month_year(query)
                if my:
                    yyyy, mm = my
                    start = datetime(yyyy, mm, 1)
                    end = start.replace(year=start.year + 1, month=1) if mm == 12 else start.replace(month=mm + 1)
                    results = list_events_from_db(start, end)
                else:
                    # Fall back to keyword search
                    with get_db_session() as db:
                        from ...domain.models import Event
                        rows = db.query(Event).filter(
                            Event.tombstoned.is_(False),
                            Event.title.ilike(f"%{query}%")
                        ).order_by(Event.start_at.desc()).limit(20).all()

                        for ev in rows:
                            results.append({
                                "id": ev.id,
                                "title": ev.title,
                                "start_at": serialize_datetime(ev.start_at),
                                "end_at": serialize_datetime(ev.end_at),
                                "location": ev.location or "",
                                "notes": ev.notes or ""
                            })

        # If no results found, show upcoming events
        if not results:
            results = list_upcoming_from_db(limit=10)

        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results)
        }

    except Exception as e:
        logger.error("Failed to search events via MCP", error=str(e))
        return {"error": f"Failed to search events: {str(e)}"}


def detect_period_from_query(query: str) -> Optional[str]:
    """Detect time period from natural language query"""
    query_lower = query.lower().strip()

    if any(word in query_lower for word in ["today", "now"]):
        return "today"
    elif any(word in query_lower for word in ["tomorrow"]):
        return "tomorrow"
    elif any(word in query_lower for word in ["this week", "week"]):
        return "week"
    elif any(word in query_lower for word in ["this month", "month"]):
        return "month"

    return None


def parse_specific_date(query: str) -> Optional[datetime]:
    """Parse specific date from query string"""
    # Try YYYY-MM-DD format
    date_pattern = r'(\d{4})-(\d{1,2})-(\d{1,2})'
    match = re.search(date_pattern, query)
    if match:
        try:
            year, month, day = map(int, match.groups())
            return datetime(year, month, day)
        except ValueError:
            pass

    # Try MM/DD/YYYY format
    date_pattern = r'(\d{1,2})/(\d{1,2})/(\d{4})'
    match = re.search(date_pattern, query)
    if match:
        try:
            month, day, year = map(int, match.groups())
            return datetime(year, month, day)
        except ValueError:
            pass

    return None


def parse_month_year(query: str) -> Optional[tuple]:
    """Parse month and year from query (e.g., 'September 2025')"""
    # Month names mapping
    months = {
        'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3,
        'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
        'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'october': 10, 'oct': 10,
        'november': 11, 'nov': 11, 'december': 12, 'dec': 12
    }

    query_lower = query.lower()

    # Look for month name and year
    for month_name, month_num in months.items():
        if month_name in query_lower:
            year_match = re.search(r'\b(20\d{2})\b', query)
            if year_match:
                year = int(year_match.group(1))
                return (year, month_num)

    return None


def compute_range_for_period(period: str, now: datetime) -> tuple:
    """Compute date range for a given period"""
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "tomorrow":
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "week":
        days_since_monday = now.weekday()
        start = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            end = start.replace(year=now.year + 1, month=1)
        else:
            end = start.replace(month=now.month + 1)
    else:
        # Default to today
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

    return start, end


def list_events_from_db(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """List events from database in date range"""
    results = []
    try:
        with get_db_session() as db:
            from ...domain.models import Event
            rows = db.query(Event).filter(
                Event.start_at >= start,
                Event.start_at < end,
                Event.tombstoned.is_(False)
            ).order_by(Event.start_at).all()

            for ev in rows:
                results.append({
                    "id": ev.id,
                    "title": ev.title,
                    "start_at": serialize_datetime(ev.start_at),
                    "end_at": serialize_datetime(ev.end_at),
                    "location": ev.location or "",
                    "notes": ev.notes or ""
                })
    except Exception as e:
        logger.error("Failed to list events from DB", error=str(e))

    return results


def list_upcoming_from_db(limit: int = 10) -> List[Dict[str, Any]]:
    """List upcoming events as fallback"""
    results = []
    try:
        with get_db_session() as db:
            from ...domain.models import Event
            now = datetime.now()
            rows = db.query(Event).filter(
                Event.start_at >= now,
                Event.tombstoned.is_(False)
            ).order_by(Event.start_at).limit(limit).all()

            for ev in rows:
                results.append({
                    "id": ev.id,
                    "title": ev.title,
                    "start_at": serialize_datetime(ev.start_at),
                    "end_at": serialize_datetime(ev.end_at),
                    "location": ev.location or "",
                    "notes": ev.notes or ""
                })
    except Exception as e:
        logger.error("Failed to list upcoming events from DB", error=str(e))

    return results
