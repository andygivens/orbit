# Apple iCloud CalDAV client
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from caldav import Calendar, DAVClient
from caldav.objects import Event as CalDAVEvent

from ..core.logging import logger


class AppleCalDAVClient:
    def __init__(
        self,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        caldav_url: Optional[str] = None,
        calendar_name: Optional[str] = None,
    ):
        # Credentials & endpoint provided dynamically from provider config
        self.username = username
        self.password = password
        self.caldav_url = caldav_url
        self.calendar_name = calendar_name
        self.override_calendar_name: Optional[str] = None
        self.client: Optional[DAVClient] = None
        self.principal = None
        self.calendars: List[Calendar] = []
        self.logger = logger.bind(component="caldav")

    def connect(self):
        """Establish connection to CalDAV server"""
        self.logger.info("Connecting to Apple CalDAV")

        if not self.username or not self.password:
            raise ValueError(
                "Apple CalDAV credentials are not configured. Update the "
                "provider settings."
            )

        try:
            self.client = DAVClient(
                url=self.caldav_url,
                username=self.username,
                password=self.password
            )

            self.principal = self.client.principal()
            self.calendars = self.principal.calendars()

            self.logger.info("CalDAV connection established",
                           calendar_count=len(self.calendars))

            for i, cal in enumerate(self.calendars):
                try:
                    cal_name = cal.name or f"Calendar {i+1}"
                    self.logger.debug("Found calendar", name=cal_name, url=cal.url)
                except Exception as e:
                    self.logger.warning("Error getting calendar info", error=str(e))

        except Exception as e:
            self.logger.error("CalDAV connection failed", error=str(e))
            raise

    def get_primary_calendar(self) -> Calendar:
        """Get the configured calendar for sync operations"""
        if not self.calendars:
            raise ValueError("No calendars available")

        # Try to find calendar by configured name
        raw_target = self.override_calendar_name or self.calendar_name
        target_name = raw_target.strip() if isinstance(raw_target, str) else None

        if target_name:
            lowered_target = target_name.lower()

            for calendar in self.calendars:
                try:
                    cal_name = (calendar.name or "").strip()
                    if cal_name and cal_name.lower() == lowered_target:
                        self.logger.info("Found configured calendar", name=cal_name)
                        return calendar
                except Exception:
                    continue

            for calendar in self.calendars:
                try:
                    props = calendar.get_properties(['{DAV:}displayname'])
                    display_name = (props.get('{DAV:}displayname', '') or "").strip()
                    if display_name and display_name.lower() == lowered_target:
                        self.logger.info(
                            "Found configured calendar by display name",
                            name=display_name,
                        )
                        return calendar
                except Exception:
                    continue

            available_names = []
            for i, cal in enumerate(self.calendars):
                try:
                    cal_name = (cal.name or f"Calendar {i+1}").strip()
                except Exception:
                    cal_name = f"Calendar {i+1}"
                available_names.append(cal_name)

            self.logger.error(
                "Configured calendar not found",
                target=target_name,
                available=available_names,
            )
            raise ValueError(
                f"Configured calendar '{target_name}' not found."
                f" Available calendars: {available_names}"
            )

        return self.calendars[0]

    def list_events(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict[str, Any]]:
        """List events in the provided date range."""
        self.logger.debug(
            "Listing CalDAV events",
            start=start_date,
            end=end_date,
        )

        if not self.calendars:
            self.connect()

        calendar = self.get_primary_calendar()

        try:
            # Search for events in the time range
            caldav_events = calendar.search(
                start=start_date,
                end=end_date,
                event=True
            )

            events = []
            for caldav_event in caldav_events:
                try:
                    parsed_event = self._parse_caldav_event(caldav_event)
                    if parsed_event:
                        events.append(parsed_event)
                except Exception as e:
                    self.logger.warning("Failed to parse CalDAV event", error=str(e))

            self.logger.info("Retrieved CalDAV events", count=len(events))
            return events

        except Exception as e:
            self.logger.error("Failed to list CalDAV events", error=str(e))
            raise

    def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new event"""
        self.logger.debug("Creating CalDAV event", title=event_data.get("title"))

        if not self.calendars:
            self.connect()

        calendar = self.get_primary_calendar()

        try:
            # Use prebuilt iCal if present
            if isinstance(event_data, dict) and event_data.get("ical"):
                ical_content = event_data["ical"]
            else:
                ical_content = self._build_ical_event(event_data)

            # Save to calendar
            caldav_event = calendar.save_event(ical_content)

            # Parse back to get the created event with UID
            created_event = self._parse_caldav_event(caldav_event)

            self.logger.info("Created CalDAV event",
                            uid=created_event.get("uid"),
                            title=created_event.get("title"))

            return created_event

        except Exception as e:
            self.logger.error("Failed to create CalDAV event", error=str(e))
            raise

    def update_event(self, uid: str, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing event"""
        self.logger.debug("Updating CalDAV event", uid=uid)

        try:
            # Find the existing event
            caldav_event = self._find_event_by_uid(uid)
            if not caldav_event:
                raise ValueError(f"Event with UID {uid} not found")

            # Update the iCalendar content. Prefer pre-rendered ICS payloads
            # so upstream converters can control UID and timezone formatting.
            if isinstance(event_data, dict) and event_data.get("ical"):
                ical_content = event_data["ical"]
                # Ensure the UID inside the ICS matches the requested UID.
                # Some converters (e.g., ProviderEventService) inject the
                # existing UID, but we defensively replace any mismatch so the
                # CalDAV server updates the intended event.
                if uid:
                    ical_content = re.sub(
                        r"UID:[^\r\n]*",
                        f"UID:{uid}",
                        ical_content,
                        count=1,
                    )
            else:
                ical_content = self._build_ical_event(event_data, uid=uid)
            caldav_event.data = ical_content
            caldav_event.save()

            # Parse back the updated event
            updated_event = self._parse_caldav_event(caldav_event)

            self.logger.info("Updated CalDAV event", uid=uid)
            return updated_event

        except Exception as e:
            self.logger.error("Failed to update CalDAV event", uid=uid, error=str(e))
            raise

    def delete_event(self, uid: str) -> bool:
        """Delete an event"""
        self.logger.debug("Deleting CalDAV event", uid=uid)

        try:
            caldav_event = self._find_event_by_uid(uid)
            if not caldav_event:
                self.logger.warning("Event not found for deletion", uid=uid)
                return False

            caldav_event.delete()
            self.logger.info("Deleted CalDAV event", uid=uid)
            return True

        except Exception as e:
            self.logger.error("Failed to delete CalDAV event", uid=uid, error=str(e))
            raise

    def get_event(self, uid: str) -> Optional[Dict[str, Any]]:
        """Get a specific event by UID"""
        try:
            caldav_event = self._find_event_by_uid(uid)
            if caldav_event:
                return self._parse_caldav_event(caldav_event)
            return None
        except Exception as e:
            self.logger.error("Failed to get CalDAV event", uid=uid, error=str(e))
            return None

    def _find_event_by_uid(self, uid: str) -> Optional[CalDAVEvent]:
        """Find a CalDAV event by its UID"""
        if not self.calendars:
            self.connect()

        calendar = self.get_primary_calendar()

        # Search for the event - this is a simplified approach
        # In production, you might want to cache UIDs for efficiency
        now = datetime.now()
        past = now - timedelta(days=365)  # Search in past year
        future = now + timedelta(days=365)  # Search in next year

        events = calendar.search(start=past, end=future, event=True)

        for event in events:
            try:
                event_data = str(event.data)
                if f"UID:{uid}" in event_data:
                    return event
            except Exception:
                continue

        return None

    def _parse_caldav_event(self, caldav_event: CalDAVEvent) -> Dict[str, Any]:
        """Parse a CalDAV event, preferring timezone-aware fields."""
        from datetime import datetime
        event_data = str(getattr(caldav_event, 'data', ''))
        # Prefer DTSTART;TZID and DTEND;TZID
        dtstart_tz = re.search(r'DTSTART;TZID=([^:]+):(\d{8}T\d{6})', event_data)
        dtend_tz = re.search(r'DTEND;TZID=([^:]+):(\d{8}T\d{6})', event_data)
        lastmod = re.search(r'LAST-MODIFIED:(\d{8}T\d{6})', event_data)
        summary = re.search(r'SUMMARY:(.+)', event_data)
        uid = re.search(r'UID:(.+)', event_data)
        location = re.search(r'LOCATION:(.+)', event_data)
        description = re.search(r'DESCRIPTION:(.+)', event_data)
        # Fallback DTSTART/DTEND
        dtstart = re.search(r'DTSTART:(\d{8}T\d{6})', event_data)
        dtend = re.search(r'DTEND:(\d{8}T\d{6})', event_data)
        # Parse dates
        def parse_dt(dtstr):
            try:
                dt = datetime.strptime(dtstr, '%Y%m%dT%H%M%S')
                if dt.year < 2000:
                    return None
                return dt
            except Exception:
                return None
        start = None
        end = None
        if dtstart_tz:
            start = parse_dt(dtstart_tz.group(2))
        elif dtstart:
            start = parse_dt(dtstart.group(1))
        if dtend_tz:
            end = parse_dt(dtend_tz.group(2))
        elif dtend:
            end = parse_dt(dtend.group(1))
        # LAST-MODIFIED
        last_modified = None
        if lastmod:
            last_modified = parse_dt(lastmod.group(1))
        return {
            "uid": uid.group(1).strip() if uid else "",
            "title": summary.group(1).strip() if summary else "",
            "description": description.group(1).strip() if description else "",
            "location": location.group(1).strip() if location else "",
            "start": start,
            "end": end,
            "last_modified": last_modified,
            "etag": getattr(caldav_event, 'etag', ''),
            "url": getattr(caldav_event, 'url', None)
        }

    def _build_ical_event(self, event_data: Dict[str, Any], uid: str = None) -> str:
        """Build iCalendar content for an event"""
        if not uid:
            uid = f"orbit-{int(datetime.now().timestamp())}"

        start_dt = event_data["start"]
        end_dt = event_data["end"]

        # Format datetimes for iCalendar
        if isinstance(start_dt, str):
            start_dt = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
        if isinstance(end_dt, str):
            end_dt = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))

        ical_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Orbit//Calendar Sync//EN
BEGIN:VEVENT
UID:{uid}
DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}
DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}
SUMMARY:{event_data.get('title', '')}
DESCRIPTION:{event_data.get('notes', '')}
LOCATION:{event_data.get('location', '')}
END:VEVENT
END:VCALENDAR"""

        return ical_content
