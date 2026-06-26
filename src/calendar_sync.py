"""Google Calendar API client for syncing film screenings."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class CalendarSync:
    """Sync film/event screenings to Google Calendar."""

    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    DEFAULT_LOCATION = "Filmhouse Cinemas, Singapore"
    TIMEZONE = "Asia/Singapore"
    SOURCE_PROPERTY = "sg_film_calendar_source"

    def __init__(self, calendar_id: str, credentials_json: str) -> None:
        self.calendar_id = calendar_id
        self.credentials = self._load_credentials(credentials_json)
        self.service = build("calendar", "v3", credentials=self.credentials)

    def _load_credentials(self, credentials_json: str):
        """Load service account credentials from JSON string."""
        info = json.loads(credentials_json)
        return service_account.Credentials.from_service_account_info(
            info, scopes=self.SCOPES
        )

    def sync_screenings(self, films: List[Dict]) -> Dict[str, int]:
        """Sync all screenings, returning operation stats."""
        stats = {"created": 0, "updated": 0, "errors": 0}

        for film in films:
            for screening in film["screenings"]:
                try:
                    self._sync_single_screening(film, screening, stats)
                except HttpError as exc:
                    stats["errors"] += 1
                    print(f"Error syncing screening: {exc}")

        return stats

    def cleanup_stale_sfs_events(self, films: List[Dict]) -> Dict[str, int]:
        """Delete stale SFS events created by older scraper versions.

        This removes:
        - legacy aggregate SFS Somerset events like "24 Jun – 28 Jun Films | SFS Somerset"
        - future stale SFS events that carry this scraper's private source marker
        """
        sfs_films = [film for film in films if film.get("source") == "sfs"]
        window = self._screening_window(sfs_films)
        if not window:
            return {"scanned": 0, "deleted": 0, "errors": 0}

        desired_ids = self._desired_event_ids(sfs_films)
        stats = {"scanned": 0, "deleted": 0, "errors": 0}

        for event in self._list_events(*window):
            stats["scanned"] += 1
            if not self._should_delete_stale_sfs_event(event, desired_ids):
                continue

            try:
                self.service.events().delete(
                    calendarId=self.calendar_id, eventId=event["id"]
                ).execute()
                stats["deleted"] += 1
            except HttpError as exc:
                stats["errors"] += 1
                print(f"Error deleting stale SFS event {event.get('summary')}: {exc}")

        return stats

    def _sync_single_screening(
        self, film: Dict, screening: Dict, stats: Dict[str, int]
    ) -> None:
        """Create or update a single screening event."""
        event_id = self._generate_event_id(film["title"], screening["start"])
        event_body = self._build_event(film, screening, event_id)

        try:
            self.service.events().insert(
                calendarId=self.calendar_id, body=event_body
            ).execute()
            stats["created"] += 1
        except HttpError as exc:
            if exc.resp.status == 409:
                self.service.events().update(
                    calendarId=self.calendar_id,
                    eventId=event_id,
                    body=event_body,
                ).execute()
                stats["updated"] += 1
            else:
                raise

    def _generate_event_id(self, title: str, start: datetime) -> str:
        """Generate a deterministic event ID for deduplication."""
        raw = f"{title}_{start.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _desired_event_ids(self, films: List[Dict]) -> Set[str]:
        """Return deterministic event IDs that should exist for these films."""
        return {
            self._generate_event_id(film["title"], screening["start"])
            for film in films
            for screening in film.get("screenings", [])
        }

    def _screening_window(
        self, films: List[Dict]
    ) -> Optional[tuple[datetime, datetime]]:
        """Return a padded time window covering the supplied screenings."""
        starts = [
            screening["start"]
            for film in films
            for screening in film.get("screenings", [])
        ]
        ends = [
            screening["end"]
            for film in films
            for screening in film.get("screenings", [])
        ]
        if not starts or not ends:
            return None
        return min(starts) - timedelta(days=1), max(ends) + timedelta(days=1)

    def _build_event(self, film: Dict, screening: Dict, event_id: str) -> Dict:
        """Build a Google Calendar event body."""
        location = film.get("venue") or self.DEFAULT_LOCATION
        source = film.get("source", "filmhouse")
        return {
            "id": event_id,
            "summary": film["title"],
            "description": self._build_description(film, screening),
            "start": {
                "dateTime": screening["start"].isoformat(),
                "timeZone": self.TIMEZONE,
            },
            "end": {
                "dateTime": screening["end"].isoformat(),
                "timeZone": self.TIMEZONE,
            },
            "location": location,
            "extendedProperties": {
                "private": {
                    self.SOURCE_PROPERTY: source,
                }
            },
        }

    def _list_events(self, start: datetime, end: datetime) -> List[Dict]:
        """List calendar events in a date window."""
        events: List[Dict] = []
        page_token = None
        while True:
            response = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=self._as_rfc3339(start),
                    timeMax=self._as_rfc3339(end),
                    singleEvents=True,
                    showDeleted=False,
                    maxResults=2500,
                    pageToken=page_token,
                )
                .execute()
            )
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return events

    @classmethod
    def _as_rfc3339(cls, value: datetime) -> str:
        """Format naive local datetimes as RFC3339 in the calendar timezone."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(cls.TIMEZONE))
        return value.isoformat()

    def _should_delete_stale_sfs_event(self, event: Dict, desired_ids: Set[str]) -> bool:
        """Return True if a listed calendar event is a stale SFS scraper event."""
        event_id = event.get("id", "")
        if event_id in desired_ids:
            return False

        if self._event_source(event) == "sfs":
            return True

        return self._is_legacy_sfs_somerset_aggregate(event)

    def _event_source(self, event: Dict) -> str:
        """Read this scraper's private source marker from a Google Calendar event."""
        return (
            event.get("extendedProperties", {})
            .get("private", {})
            .get(self.SOURCE_PROPERTY, "")
        )

    @staticmethod
    def _is_legacy_sfs_somerset_aggregate(event: Dict) -> bool:
        """Identify old aggregate SFS Somerset events from before Peatix expansion."""
        summary = event.get("summary", "")
        description = event.get("description", "")
        if "sfs somerset" not in summary.lower():
            return False
        if "films" not in summary.lower() or "|" not in summary:
            return False
        if "Category: SFS Somerset" not in description:
            return False
        return bool(
            re.search(
                r"^\s*\d{1,2}\s+[A-Za-z]+\s+[–-]\s+\d{1,2}\s+[A-Za-z]+\s+Films\s+\|",
                summary,
            )
        )

    def _build_description(self, film: Dict, screening: Dict) -> str:
        """Build event description text supporting both Filmhouse and SFS sources."""
        parts: List[str] = []

        source = film.get("source", "filmhouse")

        # Duration (SFS events may not have it, so skip if default placeholder)
        if film.get("duration_mins"):
            parts.append(f"Duration: {film['duration_mins']} minutes")

        if source == "sfs":
            # SFS-specific fields
            if film.get("category"):
                parts.append(f"Category: {film['category']}")
            if film.get("event_type"):
                parts.append(f"Type: {film['event_type']}")
            if film.get("promo_code"):
                parts.append(f"Promo code: {film['promo_code']}")
            if film.get("url"):
                parts.append(f"More info: {film['url']}")
        else:
            # Filmhouse-specific fields
            if film.get("rating"):
                parts.append(f"Rating: {film['rating']}")
            if film.get("genre"):
                parts.append(f"Genre: {film['genre']}")
            if film.get("director"):
                parts.append(f"Director: {film['director']}")
            if film.get("cast"):
                parts.append(f"Cast: {film['cast']}")

        if screening.get("booking_url"):
            parts.append(f"Book tickets: {screening['booking_url']}")

        return "\n".join(parts)
