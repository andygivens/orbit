"""
Unit tests for event mapping and conversion logic.

This is the most critical test file as it validates data conversion
between Apple CalDAV, Skylight API, and canonical formats.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data.sync_mapping import EventMappingService
from app.domain.mapping import EventMapper, ProviderEventConverter
from app.domain.models import (
    Base,
    Event,
    Provider,
    ProviderMapping,
    ProviderTypeEnum,
)


class TestProviderEventConverter:
    """Test event format conversions between providers"""

    @pytest.fixture
    def converter(self):
        return ProviderEventConverter()

    def test_apple_to_canonical_basic(self, converter):
        """Test basic Apple CalDAV event conversion"""
        apple_event = {
            'summary': 'Team Meeting',
            'dtstart': '20250908T140000',
            'dtend': '20250908T150000',
            'uid': 'apple-uid-123',
            'location': 'Conference Room A',
            'description': 'Weekly team sync meeting'
        }

        result = converter.apple_to_canonical(apple_event)

        assert result['title'] == 'Team Meeting'
        assert result['start'] == datetime(2025, 9, 8, 14, 0)
        assert result['end'] == datetime(2025, 9, 8, 15, 0)
        assert result['location'] == 'Conference Room A'
        assert result['notes'] == 'Weekly team sync meeting'
        assert result['provider_uid'] == 'apple-uid-123'
        assert result['all_day'] is False

    def test_apple_to_canonical_missing_end_time(self, converter):
        """Test Apple event without end time defaults to +1 hour"""
        apple_event = {
            'summary': 'Quick Call',
            'dtstart': '20250908T140000',
            'uid': 'apple-uid-456'
        }

        result = converter.apple_to_canonical(apple_event)

        assert result['start'] == datetime(2025, 9, 8, 14, 0)
        assert result['end'] == datetime(2025, 9, 8, 15, 0)  # +1 hour

    def test_apple_to_canonical_empty_title(self, converter):
        """Test Apple event with empty title gets default"""
        apple_event = {
            'summary': '',
            'dtstart': '20250908T140000',
            'uid': 'apple-uid-789'
        }

        result = converter.apple_to_canonical(apple_event)

        assert result['title'] == 'Untitled Event'

    def test_apple_to_canonical_ical_string_format(self, converter):
        """Test parsing Apple iCalendar string format"""
        ical_string = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-uid-ical
DTSTART:20250908T140000
DTEND:20250908T150000
SUMMARY:iCal Test Event
LOCATION:Test Location
DESCRIPTION:Test Description
END:VEVENT
END:VCALENDAR"""

        result = converter.apple_to_canonical(ical_string)

        assert result['title'] == 'iCal Test Event'
        assert result['start'] == datetime(2025, 9, 8, 14, 0)
        assert result['end'] == datetime(2025, 9, 8, 15, 0)
        assert result['location'] == 'Test Location'
        assert result['notes'] == 'Test Description'
        assert result['provider_uid'] == 'test-uid-ical'

    def test_apple_to_canonical_old_start_date_correction(self, converter):
        """Test correction of Apple events with incorrect old start dates"""
        apple_event = {
            'summary': 'Event with Bad Start',
            'dtstart': '20100101T120000',  # Old date (before 2020)
            'dtend': '20250908T150000',    # Current date
            'uid': 'apple-uid-bad-date'
        }

        result = converter.apple_to_canonical(apple_event)

        # Should use end date as start date when start is too old
        assert result['start'] == datetime(2025, 9, 8, 15, 0)
        assert result['end'] == datetime(2025, 9, 8, 16, 0)  # +1 hour from corrected start

    def test_skylight_to_canonical_basic(self, converter):
        """Test basic Skylight API event conversion"""
        skylight_event = {
            'id': 12345,
            'attributes': {
                'summary': 'Family Dinner',
                'starts_at': '2025-09-08T18:00:00-04:00',
                'ends_at': '2025-09-08T19:00:00-04:00',
                'location': 'Home',
                'description': 'Weekly family dinner',
                'timezone': 'America/New_York',
                'version': 'v1.2'
            }
        }

        result = converter.skylight_to_canonical(skylight_event)

        assert result['title'] == 'Family Dinner'
        assert result['location'] == 'Home'
        assert result['notes'] == 'Weekly family dinner'
        assert result['provider_uid'] == '12345'
        assert result['provider_uid_aliases'] == []
        assert result['timezone'] == 'America/New_York'
        assert result['version'] == 'v1.2'
        # Note: Times will be converted to local timezone

    def test_skylight_to_canonical_timezone_conversion(self, converter):
        """Test timezone handling in Skylight conversion"""
        skylight_event = {
            'id': 12346,
            'attributes': {
                'summary': 'UTC Event',
                'starts_at': '2025-09-08T20:00:00Z',
                'ends_at': '2025-09-08T21:00:00Z',
                'timezone': 'America/New_York'
            }
        }

        result = converter.skylight_to_canonical(skylight_event)

        # Should convert UTC to local time (EST/EDT)
        assert result['start'] is not None
        assert result['end'] is not None

    def test_skylight_to_canonical_includes_aliases(self, converter):
        skylight_event = {
            'id': '2834018240-1760477400',
            'attributes': {
                'summary': 'Alias Sample',
                'starts_at': '2025-09-08T18:00:00-04:00',
                'ends_at': '2025-09-08T19:00:00-04:00',
                'timezone': 'America/New_York',
                'uid': 'orbit-1757023815',
                'source_uid': '0477E3DD-CDB0-49DB-BF25-B7B931AFCA38'
            }
        }

        result = converter.skylight_to_canonical(skylight_event)

        assert result['provider_uid'] == '2834018240-1760477400'
        assert set(result['provider_uid_aliases']) == {
            'orbit-1757023815',
            '0477E3DD-CDB0-49DB-BF25-B7B931AFCA38'
        }

    def test_canonical_to_skylight_basic(self, converter):
        """Test canonical to Skylight API format conversion"""
        canonical_event = {
            'title': 'Test Event',
            'start': datetime(2025, 9, 8, 14, 0),
            'end': datetime(2025, 9, 8, 15, 0),
            'location': 'Office',
            'notes': 'Important meeting',
            'timezone': 'America/New_York',
            'category_ids': [1, 2]
        }

        result = converter.canonical_to_skylight(canonical_event)

        assert result['summary'] == 'Test Event'
        assert result['kind'] == 'standard'
        assert result['category_ids'] == [1, 2]
        assert result['location'] == 'Office'
        assert result['description'] == 'Important meeting'
        assert result['timezone'] == 'America/New_York'
        assert result['all_day'] is False
        assert 'starts_at' in result
        assert 'ends_at' in result

    def test_canonical_to_skylight_missing_title(self, converter):
        """Test Skylight conversion handles missing title"""
        canonical_event = {
            'title': '',
            'start': datetime(2025, 9, 8, 14, 0),
            'end': datetime(2025, 9, 8, 15, 0)
        }

        result = converter.canonical_to_skylight(canonical_event)

        assert result['summary'] == 'Untitled Event'

    def test_canonical_to_skylight_missing_times(self, converter):
        """Test Skylight conversion handles missing start/end times"""
        canonical_event = {
            'title': 'Event without times'
        }

        result = converter.canonical_to_skylight(canonical_event)

        # Should get default times
        assert result['summary'] == 'Event without times'
        assert 'starts_at' in result
        assert 'ends_at' in result

    def test_canonical_to_apple_basic(self, converter):
        """Test canonical to Apple CalDAV format conversion"""
        canonical_event = {
            'title': 'Apple Test Event',
            'start': datetime(2025, 9, 8, 14, 0),
            'end': datetime(2025, 9, 8, 15, 0),
            'location': 'Apple Office',
            'notes': 'Test meeting with Apple team',
            'provider_uid': 'test-apple-uid'
        }

        result = converter.canonical_to_apple(canonical_event)

        assert result['uid'] == 'test-apple-uid'
        assert 'ical' in result

        # Check iCalendar content
        ical = result['ical']
        assert 'SUMMARY:Apple Test Event' in ical
        assert 'DTSTART:20250908T140000' in ical
        assert 'DTEND:20250908T150000' in ical
        assert 'LOCATION:Apple Office' in ical
        assert 'DESCRIPTION:Test meeting with Apple team' in ical

    def test_canonical_to_apple_missing_times(self, converter):
        """Test Apple conversion handles missing times"""
        canonical_event = {
            'title': 'Event without times'
        }

        result = converter.canonical_to_apple(canonical_event)

        # Should return None for invalid events
        assert result is None

    def test_parse_datetime_various_formats(self, converter):
        """Test _parse_datetime handles various input formats"""
        # Test datetime object
        dt = datetime(2025, 9, 8, 14, 0)
        assert converter._parse_datetime(dt) == dt

        # Test ISO string
        iso_str = '2025-09-08T14:00:00'
        result = converter._parse_datetime(iso_str)
        assert result == datetime(2025, 9, 8, 14, 0)

        # Test ISO string with timezone
        iso_tz = '2025-09-08T14:00:00Z'
        result = converter._parse_datetime(iso_tz)
        assert result == datetime(2025, 9, 8, 14, 0)

        # Test None
        assert converter._parse_datetime(None) is None

        # Test invalid format
        assert converter._parse_datetime('invalid') is None


class TestEventMapper:
    """Test event mapping and deduplication logic"""

    @pytest.fixture
    def mapper(self):
        return EventMapper()

    def test_find_duplicate_event_exact_match(self, mapper):
        """Test finding exact duplicate events"""
        existing_events = [
            Event(
                id='existing-1',
                title='Team Meeting',
                start_at=datetime(2025, 9, 8, 14, 0),
                end_at=datetime(2025, 9, 8, 15, 0),
                tombstoned=False
            )
        ]

        candidate = {
            'title': 'Team Meeting',
            'start_at': datetime(2025, 9, 8, 14, 0)
        }

        duplicate = mapper.find_duplicate_event(existing_events, candidate)

        assert duplicate is not None
        assert duplicate.id == 'existing-1'

    def test_find_duplicate_event_time_tolerance(self, mapper):
        """Test duplicate detection with time tolerance (within 2 minutes)"""
        existing_events = [
            Event(
                id='existing-1',
                title='Team Meeting',
                start_at=datetime(2025, 9, 8, 14, 0),
                end_at=datetime(2025, 9, 8, 15, 0),
                tombstoned=False
            )
        ]

        # Event 1 minute later should be detected as duplicate
        candidate = {
            'title': 'Team Meeting',
            'start_at': datetime(2025, 9, 8, 14, 1)
        }

        duplicate = mapper.find_duplicate_event(existing_events, candidate)
        assert duplicate is not None

        # Event 3 minutes later should NOT be detected as duplicate
        candidate_far = {
            'title': 'Team Meeting',
            'start_at': datetime(2025, 9, 8, 14, 3)
        }

        duplicate_far = mapper.find_duplicate_event(existing_events, candidate_far)
        assert duplicate_far is None

    def test_find_duplicate_event_title_normalization(self, mapper):
        """Test duplicate detection with normalized titles"""
        existing_events = [
            Event(
                id='existing-1',
                title='  Team Meeting  ',  # With spaces
                start_at=datetime(2025, 9, 8, 14, 0),
                end_at=datetime(2025, 9, 8, 15, 0),
                tombstoned=False
            )
        ]

        candidate = {
            'title': 'TEAM MEETING',  # Different case
            'start_at': datetime(2025, 9, 8, 14, 0)
        }

        duplicate = mapper.find_duplicate_event(existing_events, candidate)
        assert duplicate is not None

    def test_find_duplicate_event_skips_tombstoned(self, mapper):
        """Test that tombstoned events are ignored in duplicate detection"""
        existing_events = [
            Event(
                id='tombstoned-1',
                title='Team Meeting',
                start_at=datetime(2025, 9, 8, 14, 0),
                end_at=datetime(2025, 9, 8, 15, 0),
                tombstoned=True  # This should be ignored
            )
        ]

        candidate = {
            'title': 'Team Meeting',
            'start_at': datetime(2025, 9, 8, 14, 0)
        }

        duplicate = mapper.find_duplicate_event(existing_events, candidate)
        assert duplicate is None

    def test_create_dedup_key_consistent(self, mapper):
        """Test deduplication key creation is consistent"""
        title = "Team Meeting"
        start = datetime(2025, 9, 8, 14, 0)
        organizer = "john@example.com"

        key1 = mapper.create_dedup_key(title, start, organizer)
        key2 = mapper.create_dedup_key(title, start, organizer)

        assert key1 == key2
        assert len(key1) == 32  # MD5 hash length

    def test_create_dedup_key_different_inputs(self, mapper):
        """Test deduplication keys differ for different inputs"""
        base_start = datetime(2025, 9, 8, 14, 0)

        key1 = mapper.create_dedup_key("Meeting A", base_start)
        key2 = mapper.create_dedup_key("Meeting B", base_start)
        key3 = mapper.create_dedup_key("Meeting A", base_start + timedelta(minutes=1))

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

    def test_normalize_title(self, mapper):
        """Test title normalization"""
        assert mapper._normalize_title("  Team Meeting  ") == "team meeting"
        assert mapper._normalize_title("IMPORTANT CALL") == "important call"
        assert mapper._normalize_title("") == ""

    def test_round_to_minute(self, mapper):
        """Test datetime rounding to minute"""
        dt_with_seconds = datetime(2025, 9, 8, 14, 30, 45, 123456)
        rounded = mapper._round_to_minute(dt_with_seconds)

        assert rounded == datetime(2025, 9, 8, 14, 30, 0, 0)


class TestDateTimeEdgeCases:
    """Test edge cases in datetime handling"""

    @pytest.fixture
    def converter(self):
        return ProviderEventConverter()

    def test_parse_ical_datetime_formats(self, converter):
        """Test various iCalendar datetime formats"""
        # Basic format
        result1 = converter._parse_ical_datetime('20250908T140000')
        assert result1 == datetime(2025, 9, 8, 14, 0)

        # With Z suffix
        result2 = converter._parse_ical_datetime('20250908T140000Z')
        assert result2 == datetime(2025, 9, 8, 14, 0)

        # Date only (all-day)
        result3 = converter._parse_ical_datetime('20250908')
        assert result3 == datetime(2025, 9, 8, 0, 0)

        # Invalid format
        result4 = converter._parse_ical_datetime('invalid-date')
        assert result4 is None

    def test_timezone_edge_cases(self, converter):
        """Test timezone handling edge cases"""
        # Test with unknown timezone fallback
        canonical_event = {
            'title': 'TZ Test',
            'start': datetime(2025, 9, 8, 14, 0),
            'end': datetime(2025, 9, 8, 15, 0),
            'timezone': 'Unknown/Timezone'
        }

        result = converter.canonical_to_skylight(canonical_event)

        # Should fallback to America/New_York
        assert result['timezone'] == 'America/New_York'


# Test fixtures and helpers
@pytest.fixture
def sample_apple_event():
    """Sample Apple CalDAV event for testing"""
    return {
        'summary': 'Sample Apple Event',
        'dtstart': '20250908T140000',
        'dtend': '20250908T150000',
        'uid': 'apple-sample-123',
        'location': 'Apple Campus',
        'description': 'Sample description'
    }

@pytest.fixture
def sample_skylight_event():
    """Sample Skylight API event for testing"""
    return {
        'id': 54321,
        'attributes': {
            'summary': 'Sample Skylight Event',
            'starts_at': '2025-09-08T14:00:00-04:00',
            'ends_at': '2025-09-08T15:00:00-04:00',
            'location': 'Skylight HQ',
            'description': 'Sample description',
            'timezone': 'America/New_York'
        }
    }

@pytest.fixture
def sample_canonical_event():
    """Sample canonical event for testing"""
    return {
        'title': 'Sample Canonical Event',
        'start': datetime(2025, 9, 8, 14, 0),
        'end': datetime(2025, 9, 8, 15, 0),
        'location': 'Meeting Room',
        'notes': 'Sample notes',
        'provider_uid': 'canonical-123',
        'timezone': 'America/New_York'
    }


@pytest.fixture
def in_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def seeded_entities(in_memory_session):
    event = Event(
        id="event-1",
        title="Alias Test",
        start_at=datetime(2025, 10, 3, 17, 30, tzinfo=timezone.utc),
        end_at=datetime(2025, 10, 3, 23, 0, tzinfo=timezone.utc),
        location="",
        notes="",
    )
    event.update_content_hash()

    provider = Provider(
        id="provider-apple",
        type=ProviderTypeEnum.APPLE_CALDAV,
        type_id=ProviderTypeEnum.APPLE_CALDAV.value,
        name="Apple Test",
        config={},
    )

    in_memory_session.add_all([event, provider])
    in_memory_session.commit()
    return event, provider


class TestEventMappingServiceUpsert:
    def test_reuses_mapping_when_provider_uid_changes(
        self,
        in_memory_session,
        seeded_entities,
    ):
        service = EventMappingService(in_memory_session)
        event, provider = seeded_entities

        first = service.upsert_mapping(
            provider_id=provider.id,
            provider_type=ProviderTypeEnum.APPLE_CALDAV,
            provider_uid="orbit-1757023815",
            orbit_event_id=event.id,
            alternate_uids=["legacy-guid"],
        )
        in_memory_session.flush()
        original_mapping_id = first.id

        second = service.upsert_mapping(
            provider_id=provider.id,
            provider_type=ProviderTypeEnum.APPLE_CALDAV,
            provider_uid="3368047932",
            orbit_event_id=event.id,
        )
        in_memory_session.flush()

        mappings = (
            in_memory_session.query(ProviderMapping)
            .filter(ProviderMapping.provider_id == provider.id)
            .all()
        )

        assert len(mappings) == 1
        mapping = mappings[0]
        assert mapping.id == original_mapping_id
        assert mapping.provider_uid == "3368047932"
        assert second.id == first.id
        assert set(mapping.alternate_uids or []) == {
            "orbit-1757023815",
            "legacy-guid",
        }
