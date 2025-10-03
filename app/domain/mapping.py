# Event mapping and deduplication logic
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from ..core.logging import logger
from ..domain.models import Event, ProviderEnum, ProviderMapping


class EventMapper:
    def __init__(self):
        self.logger = logger.bind(component="mapper")

    def find_duplicate_event(
        self,
        events: List[Event],
        candidate_event: dict,
    ) -> Optional[Event]:
        """Find if a candidate event already exists in the list"""
        candidate_title = self._normalize_title(candidate_event.get("title", ""))
        candidate_start = (
            candidate_event.get("start_at")
            or candidate_event.get("start")
        )

        if not candidate_start:
            return None

        # Convert to datetime if it's a string
        if isinstance(candidate_start, str):
            candidate_start = datetime.fromisoformat(
                candidate_start.replace("Z", "+00:00")
            )

        for event in events:
            if event.tombstoned:
                continue

            # Check normalized title match
            if self._normalize_title(event.title) != candidate_title:
                continue

            # Check time proximity (within 2 minutes)
            time_diff = abs((event.start_at - candidate_start).total_seconds())
            if time_diff <= 120:  # 2 minutes tolerance
                self.logger.debug(
                    "Found duplicate event",
                    orbit_event_id=event.id,
                    title=event.title,
                    time_diff_sec=time_diff,
                )
                return event

        return None

    def find_event_by_provider_uid(
        self,
        mappings: List[ProviderMapping],
        provider: ProviderEnum,
        provider_uid: str,
    ) -> Optional[str]:
        """Find orbit ID by provider UID"""
        for mapping in mappings:
            if mapping.provider_uid != provider_uid:
                continue
            if mapping.provider_type:
                if mapping.provider_type.value == provider.value:
                    return mapping.orbit_event_id
            elif mapping.provider and mapping.provider.type:
                if mapping.provider.type.value == provider.value:
                    return mapping.orbit_event_id
        return None

    def create_dedup_key(
        self,
        title: str,
        start: datetime,
        organizer: str = None,
    ) -> str:
        """Create a deduplication key for an event"""
        normalized_title = self._normalize_title(title)
        start_rounded = self._round_to_minute(start)
        organizer_part = organizer or ""

        key_content = f"{normalized_title}|{start_rounded.isoformat()}|{organizer_part}"
        return hashlib.md5(key_content.encode()).hexdigest()

    def _normalize_title(self, title: str) -> str:
        """Normalize event title for comparison"""
        return title.strip().lower()

    def _round_to_minute(self, dt: datetime) -> datetime:
        """Round datetime to the nearest minute"""
        return dt.replace(second=0, microsecond=0)


class ProviderEventConverter:
    """Convert between provider-specific event formats and our canonical format"""

    def __init__(self):
        self.logger = logger.bind(component="converter")

    def apple_to_canonical(self, apple_event: dict) -> dict:
        """Convert Apple CalDAV event to canonical format"""
        try:
            # Apple events come in as raw iCalendar strings, we need to
            # parse them properly.
            if isinstance(apple_event, str):
                # Parse the iCalendar data
                lines = apple_event.split('\n')
                event_data = {}

                for line in lines:
                    line = line.strip()
                    if line.startswith('SUMMARY:'):
                        event_data['summary'] = line[8:].strip()
                    elif line.startswith('UID:'):
                        event_data['uid'] = line[4:].strip()
                    elif line.startswith('DTSTART'):
                        # Handle both DTSTART:VALUE and DTSTART;VALUE formats
                        if ':' in line:
                            date_str = line.split(':', 1)[1].strip()
                            self.logger.debug("Parsing DTSTART", raw=date_str)
                            event_data['dtstart'] = self._parse_ical_datetime(date_str)
                    elif line.startswith('DTEND'):
                        if ':' in line:
                            date_str = line.split(':', 1)[1].strip()
                            self.logger.debug("Parsing DTEND", raw=date_str)
                            event_data['dtend'] = self._parse_ical_datetime(date_str)
                    elif line.startswith('LOCATION:'):
                        event_data['location'] = line[9:].strip()
                    elif line.startswith('DESCRIPTION:'):
                        event_data['description'] = line[12:].strip()
            else:
                # Handle dict format (from our CalDAV client)
                self.logger.debug("Apple event data", apple_event=apple_event)
                event_data = apple_event

            # Extract and validate data
            title = event_data.get('summary', event_data.get('title', 'Untitled Event'))
            if not title or title.strip() == '':
                title = 'Untitled Event'
            start_dt = event_data.get('dtstart', event_data.get('start'))
            end_dt = event_data.get('dtend', event_data.get('end'))

            # Debug the raw dates we're getting
            self.logger.debug(
                "Raw Apple dates",
                start_raw=start_dt,
                end_raw=end_dt,
                title=title,
            )

            # Handle Apple's weird date behavior - sometimes START is wrong/old
            # If START is clearly wrong (before 2020), prefer END date
            if start_dt and end_dt:
                from datetime import datetime

                # Events before this date are likely old/incorrect snapshots.
                cutoff_date = datetime(2020, 1, 1)

                if isinstance(start_dt, str):
                    start_dt = self._parse_ical_datetime(start_dt)
                if isinstance(end_dt, str):
                    end_dt = self._parse_ical_datetime(end_dt)

                # If start is before cutoff but end is after, use end as start
                if (
                    start_dt
                    and end_dt
                    and start_dt < cutoff_date
                    and end_dt > cutoff_date
                ):
                    self.logger.info(
                        "Detected likely wrong START date, using END as START",
                        start=start_dt.isoformat() if start_dt else None,
                        end=end_dt.isoformat() if end_dt else None,
                    )
                    start_dt = end_dt
                    # Add 1 hour for end time
                    from datetime import timedelta
                    end_dt = start_dt + timedelta(hours=1)

            # Ensure we have valid end time - add 1 hour if missing
            if start_dt and not end_dt:
                from datetime import timedelta
                if isinstance(start_dt, str):
                    start_dt = self._parse_ical_datetime(start_dt)
                if start_dt:
                    end_dt = start_dt + timedelta(hours=1)

            # Debug logging for full event details (only if DEBUG)
            import os
            if os.environ.get('ORBIT_LOG_LEVEL', '').upper() == 'DEBUG':
                self.logger.debug(
                    "Apple event (raw)",
                    apple_event_data=event_data,
                )
                self.logger.debug(
                    "Apple event (human)",
                    apple_event_title=title,
                    apple_event_start=start_dt,
                    apple_event_end=end_dt,
                    apple_event_location=event_data.get('location', ''),
                    apple_event_description=event_data.get('description', ''),
                )

            return {
                "title": title.strip(),
                "start": start_dt,
                "end": end_dt,
                "location": event_data.get('location', ''),
                "notes": event_data.get('description', event_data.get('notes', '')),
                "provider_uid": event_data.get('uid', ''),
                "all_day": False  # We'll enhance this later
            }
        except Exception as e:
            self.logger.error(
                "Failed to convert Apple event",
                error_msg=str(e),
                apple_event=apple_event,
            )
            raise

    def _parse_ical_datetime(self, date_str: str):
        """Parse iCalendar datetime string to Python datetime"""
        try:
            from datetime import datetime

            # Clean the date string
            date_str = date_str.strip()

            # Debug log the raw date string we're trying to parse
            self.logger.debug("Parsing iCal date", raw_date=date_str)

            # Handle different iCalendar formats
            if 'T' in date_str:
                # Format: 20250904T130000 or 20250904T130000Z
                clean_date = date_str.replace('Z', '')
                if len(clean_date) >= 15:
                    parsed = datetime.strptime(clean_date[:15], '%Y%m%dT%H%M%S')
                    self.logger.debug(
                        "Parsed iCal datetime",
                        raw=date_str,
                        parsed=parsed.isoformat(),
                    )
                    return parsed
            elif len(date_str) == 8:
                # Format: 20250904 (all-day event)
                parsed = datetime.strptime(date_str, '%Y%m%d')
                self.logger.debug(
                    "Parsed iCal date",
                    raw=date_str,
                    parsed=parsed.isoformat(),
                )
                return parsed

            # Try parsing as ISO format as fallback
            if 'T' in date_str:
                parsed = datetime.fromisoformat(date_str.replace('Z', ''))
                self.logger.debug(
                    "Parsed ISO datetime",
                    raw=date_str,
                    parsed=parsed.isoformat(),
                )
                return parsed

            self.logger.warning("Unrecognized date format", date_str=date_str)
            return None

        except Exception as e:
            self.logger.error(
                "Failed to parse datetime",
                date_str=date_str,
                error=str(e),
            )
            return None

    def skylight_to_canonical(self, skylight_event: dict) -> dict:
        """Convert Skylight API event to canonical format with local timezone."""
        try:
            data = skylight_event
            if isinstance(skylight_event, dict) and "data" in skylight_event and isinstance(skylight_event["data"], dict):
                data = skylight_event["data"]
            attrs = data.get('attributes', data)
            tz_name = attrs.get('timezone', 'UTC')
            starts_at = attrs.get('starts_at', attrs.get('start_time'))
            ends_at = attrs.get('ends_at', attrs.get('end_time'))
            raw_primary_id = data.get('id', skylight_event.get('id'))
            primary_id = raw_primary_id or attrs.get('uid') or attrs.get('id')
            aliases: List[str] = []

            def _collect_alias(candidate):
                if not candidate:
                    return
                try:
                    text = str(candidate)
                except Exception:
                    return
                if not text.strip():
                    return
                if primary_id is not None and text == str(primary_id):
                    return
                if text not in aliases:
                    aliases.append(text)

            _collect_alias(attrs.get('uid'))
            _collect_alias(attrs.get('original_uid'))
            _collect_alias(attrs.get('source_uid'))

            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo
            def to_local(dt_str, tz):
                if not dt_str:
                    return None
                try:
                    dt = _dt.fromisoformat(dt_str.replace('Z', '+00:00'))
                    # Convert to local time in tz_name
                    return dt.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
                except Exception:
                    return None
            start_local = to_local(starts_at, tz_name)
            end_local = to_local(ends_at, tz_name)
            return {
                "title": attrs.get("summary", attrs.get("title", "")),
                "start": start_local,
                "end": end_local,
                "location": attrs.get("location", ""),
                "notes": attrs.get("description", ""),
                "provider_uid": str(primary_id) if primary_id is not None else "",
                "provider_uid_aliases": aliases,
                "version": attrs.get("version", ""),
                "timezone": tz_name
            }
        except Exception as e:
            self.logger.error(
                "Failed to convert Skylight event",
                error=str(e),
                skylight_event=skylight_event,
            )
            raise

    def canonical_to_apple(
        self,
        canonical_event: dict,
        existing_uid: Optional[str] = None,
    ) -> dict:
        """Convert canonical event to Apple CalDAV format"""
        try:
            start_dt = self._parse_datetime(canonical_event.get("start"))
            end_dt = self._parse_datetime(canonical_event.get("end"))
            if not start_dt or not end_dt:
                self.logger.warning(
                    "Cannot convert event to Apple format: missing start or end",
                    canonical_event=canonical_event,
                )
                return None

            uid = (
                existing_uid
                or canonical_event.get("apple_uid")
                or canonical_event.get("provider_uid")
            )
            if not uid:
                uid = f"orbit-{uuid.uuid4().hex}"

            # Ensure naive format for iCalendar export
            start_str = start_dt.replace(tzinfo=None).strftime("%Y%m%dT%H%M%S")
            end_str = end_dt.replace(tzinfo=None).strftime("%Y%m%dT%H%M%S")

            # Format for iCalendar
            ical_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Orbit//Calendar Sync//EN
BEGIN:VEVENT
UID:{uid}
DTSTART:{start_str}
DTEND:{end_str}
SUMMARY:{canonical_event['title']}
DESCRIPTION:{canonical_event.get('notes', '')}
LOCATION:{canonical_event.get('location', '')}
END:VEVENT
END:VCALENDAR"""

            return {
                "ical": ical_content,
                "uid": uid,
            }
        except Exception as e:
            self.logger.error(
                "Failed to convert to Apple format",
                error=str(e),
                canonical_event=canonical_event,
            )
            raise

    def canonical_to_skylight(self, canonical_event: dict) -> dict:
        """Convert canonical event to Skylight payload with timezone awareness."""
        try:
            import pytz
            # Ensure we have required fields
            title = canonical_event.get("title", "").strip()
            if not title:
                title = "Untitled Event"

            # Determine timezone
            tz_name = canonical_event.get("timezone") or "America/New_York"
            try:
                tzinfo = pytz.timezone(tz_name)
            except Exception:
                tzinfo = pytz.timezone("America/New_York")
                tz_name = "America/New_York"

            # Parse datetimes and localize if needed
            start_dt = self._parse_datetime(canonical_event.get("start"))
            end_dt = self._parse_datetime(canonical_event.get("end"))
            if start_dt and start_dt.tzinfo is None:
                start_dt = tzinfo.localize(start_dt)
            if end_dt and end_dt.tzinfo is None:
                end_dt = tzinfo.localize(end_dt)

            # Fallback dates if missing
            if not start_dt:
                now = datetime.now(tzinfo)
                start_dt = now
                end_dt = now + timedelta(hours=1)
            elif not end_dt:
                end_dt = start_dt + timedelta(hours=1)

            starts_at = start_dt.isoformat()
            ends_at = end_dt.isoformat()

            # Get category IDs if provided by caller
            category_ids = canonical_event.get("category_ids", [])

            # Debug logging for Skylight request (only if DEBUG)
            import os
            if os.environ.get('ORBIT_LOG_LEVEL', '').upper() == 'DEBUG':
                events_url = (
                    "https://app.ourskylight.com/api/frames/<FRAME_ID>/"
                    "calendar_events"
                )
                self.logger.debug(
                    "Skylight request",
                    url=events_url,
                    body=canonical_event,
                )

            # Use the expected Skylight JSON format
            return {
                "summary": title,
                "kind": "standard",
                "category_ids": category_ids,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "all_day": canonical_event.get("all_day", False),
                "rrule": None,
                "invited_emails": [],
                "location": canonical_event.get("location", ""),
                "lat": None,
                "lng": None,
                "description": canonical_event.get("notes", ""),
                "calendar_account_id": None,
                "calendar_id": None,
                "timezone": tz_name,
                "event_notification_setting_attributes": None,
                "countdown_enabled": False
            }
        except Exception as e:
            self.logger.error(
                "Failed to convert to Skylight format",
                error=str(e),
                canonical_event=canonical_event,
            )
            raise

    def _parse_datetime(self, dt_input) -> Optional[datetime]:
        """Parse datetime from various input formats"""
        if not dt_input:
            return None

        if isinstance(dt_input, datetime):
            return dt_input

        if isinstance(dt_input, str):
            # Handle ISO format with timezone
            try:
                parsed = datetime.fromisoformat(dt_input.replace('Z', '+00:00'))
                return parsed.replace(tzinfo=None)
            except ValueError:
                pass

            # Handle other common formats
            for fmt in ['%Y%m%dT%H%M%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']:
                try:
                    return datetime.strptime(dt_input, fmt)
                except ValueError:
                    continue

        self.logger.warning("Could not parse datetime", input=dt_input)
        return None
