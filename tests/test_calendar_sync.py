from datetime import datetime, timedelta

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from calendar_sync import CalendarSync


class _Executable:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeEvents:
    def __init__(self, items):
        self.items = items
        self.deleted = []

    def list(self, **kwargs):
        return _Executable({"items": self.items})

    def delete(self, calendarId, eventId):
        self.deleted.append((calendarId, eventId))
        return _Executable({})


class _FakeService:
    def __init__(self, items):
        self.events_resource = _FakeEvents(items)

    def events(self):
        return self.events_resource


def _sync_without_google(items):
    sync = CalendarSync.__new__(CalendarSync)
    sync.calendar_id = "calendar@example.com"
    sync.service = _FakeService(items)
    return sync


def test_verify_sfs_events_reports_missing_screenings_and_remaining_aggregates():
    sync_for_ids = CalendarSync.__new__(CalendarSync)
    films = [
        {
            "title": "BLUE VELVET",
            "source": "sfs",
            "screenings": [
                {
                    "start": datetime(2026, 7, 17, 19, 30),
                    "end": datetime(2026, 7, 17, 21, 30),
                }
            ],
        },
        {
            "title": "THE WAVES WILL CARRY US",
            "source": "sfs",
            "screenings": [
                {
                    "start": datetime(2026, 7, 19, 19, 30),
                    "end": datetime(2026, 7, 19, 21, 30),
                }
            ],
        },
    ]
    blue_velvet_id = sync_for_ids._generate_event_id(
        "BLUE VELVET", films[0]["screenings"][0]["start"]
    )
    sync = _sync_without_google(
        [
            {
                "id": blue_velvet_id,
                "summary": "BLUE VELVET",
                "start": {"dateTime": "2026-07-17T19:30:00+08:00"},
                "status": "confirmed",
                "htmlLink": "https://calendar.google.com/event?blue-velvet",
            },
            {
                "id": "aggregate",
                "summary": "17 Jul – 19 Jul Films | SFS Somerset",
            },
        ]
    )

    result = sync.verify_sfs_events(films)

    assert result == {
        "expected": 2,
        "found": 1,
        "missing": ["THE WAVES WILL CARRY US @ 2026-07-19 19:30"],
        "legacy_aggregates": ["17 Jul – 19 Jul Films | SFS Somerset"],
        "latest_events": [
            {
                "label": "BLUE VELVET @ 2026-07-17 19:30",
                "summary": "BLUE VELVET",
                "start": "2026-07-17T19:30:00+08:00",
                "status": "confirmed",
                "html_link": "https://calendar.google.com/event?blue-velvet",
            }
        ],
    }


def test_build_event_marks_source_for_future_stale_cleanup():
    sync = CalendarSync.__new__(CalendarSync)
    film = {"title": "BLUE VELVET", "source": "sfs", "screenings": []}
    screening = {
        "start": datetime(2026, 7, 1, 19, 30),
        "end": datetime(2026, 7, 1, 21, 30),
    }

    event = sync._build_event(film, screening, "eventid")

    assert event["extendedProperties"]["private"] == {
        CalendarSync.SOURCE_PROPERTY: "sfs"
    }


def test_cleanup_deletes_legacy_somerset_aggregates_and_marked_stale_sfs_events():
    sync_for_ids = CalendarSync.__new__(CalendarSync)
    film = {
        "title": "BLUE VELVET",
        "source": "sfs",
        "screenings": [
            {
                "start": datetime(2026, 6, 24, 19, 30),
                "end": datetime(2026, 6, 24, 21, 30),
            }
        ],
    }
    desired_id = sync_for_ids._generate_event_id("BLUE VELVET", film["screenings"][0]["start"])

    items = [
        {
            "id": desired_id,
            "summary": "BLUE VELVET",
            "extendedProperties": {
                "private": {CalendarSync.SOURCE_PROPERTY: "sfs"}
            },
        },
        {
            "id": "old_marked_sfs",
            "summary": "OLD SFS EVENT",
            "extendedProperties": {
                "private": {CalendarSync.SOURCE_PROPERTY: "sfs"}
            },
        },
        {
            "id": "legacy_aggregate",
            "summary": "24 Jun – 28 Jun Films | SFS Somerset",
            "description": "Duration: 120 minutes\nCategory: SFS Somerset\nType: Discount",
        },
        {
            "id": "legacy_aggregate_without_current_description",
            "summary": "9 Jul – 12 Jul Films | SFS Somerset",
        },
        {
            "id": "unrelated",
            "summary": "Personal reminder",
            "description": "Category: something else",
        },
    ]
    sync = _sync_without_google(items)

    stats = sync.cleanup_stale_sfs_events([film])

    assert stats == {"scanned": 5, "deleted": 3, "errors": 0}
    assert sync.service.events_resource.deleted == [
        ("calendar@example.com", "old_marked_sfs"),
        ("calendar@example.com", "legacy_aggregate"),
        ("calendar@example.com", "legacy_aggregate_without_current_description"),
    ]
