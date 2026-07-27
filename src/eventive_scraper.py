"""Scraper for Singapore Film Society's Eventive schedule.

SFS has migrated its ticketing and schedule from Peatix / a published Google
Sheet to an Eventive virtual box office at
``https://singaporefilmsociety.eventive.org/schedule``. The schedule page itself
is a single-page app whose HTML shell carries no data, so this scraper reads
Eventive's JSON API instead — discovered from the schedule page's tenant bundle
— using the same ``scrapling`` ``Fetcher`` the rest of the project relies on.

Each API event is one screening (with a start/end time, a venue, and the full
film object inline carrying director/cast/poster/synopsis and structured
``details`` — runtime, rating, language, country, genre, production year). We
emit one ``film`` dict per Eventive film with all of its screenings grouped
under it, in the exact shape ``calendar_sync`` and ``history`` already consume
for the Peatix-based SFS source, so the downstream pipeline is unchanged.
"""

import html
import json
import re
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from scrapling.fetchers import Fetcher

SCHEDULE_URL = "https://singaporefilmsociety.eventive.org/schedule"
API_BASE = "https://api.eventive.org"

# Fallbacks used when the tenant bundle on the schedule page can't be parsed.
# These are SFS's public, non-secret Eventive identifiers (the same values the
# schedule page exposes in its client-side JS).
DEFAULT_EVENT_BUCKET = "6a277454f068b0ba9c60baae"
DEFAULT_API_KEY = "64e43fe498039a1baf38b8635ec700a4"

# Eventive tag names that denote an SFS curatorial programme (e.g. "SFS
# Somerset", "SFS Showcase"). Pricing tags like "$6 Off for Members" are
# excluded so that programmes — the historic-archive theme — stay clean.
PROGRAMME_TAG_PREFIX = "SFS "

TIMEZONE = ZoneInfo("Asia/Singapore")


class EventiveScraper:
    """Scrape SFS screenings from their Eventive schedule via the JSON API."""

    SCHEDULE_URL = SCHEDULE_URL
    API_BASE = API_BASE
    DEFAULT_EVENT_BUCKET = DEFAULT_EVENT_BUCKET
    DEFAULT_API_KEY = DEFAULT_API_KEY

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now()

    def scrape(self) -> List[Dict]:
        """Fetch and parse all SFS screenings from the Eventive schedule."""
        event_bucket, api_key = self._resolve_credentials()
        payload = self._fetch_events(event_bucket, api_key)
        events = payload.get("events") or []
        return self._build_films(events)

    # -- credential discovery ------------------------------------------------

    def _resolve_credentials(self) -> tuple[str, str]:
        """Find the Eventive event bucket id + api key from the schedule page.

        The schedule page loads a tenant JS bundle (``<script data-type=...>``)
        that defines a ``TENANT`` object with ``event_bucket`` and ``api_key``.
        Falling back to the hardcoded constants keeps the scraper working if the
        page markup changes.
        """
        bucket, api_key = self.DEFAULT_EVENT_BUCKET, self.DEFAULT_API_KEY
        try:
            tenant_src = self._tenant_script_src()
            if tenant_src:
                bundle = self._fetch_text(tenant_src)
                found_bucket = re.search(r'"event_bucket"\s*:\s*"([^"]+)"', bundle)
                found_key = re.search(r'"api_key"\s*:\s*"([^"]+)"', bundle)
                if found_bucket and found_key:
                    bucket, api_key = found_bucket.group(1), found_key.group(1)
        except Exception as exc:  # noqa: BLE001 - keep working with fallbacks
            print(f"  ! could not parse Eventive tenant bundle: {exc}")
        return bucket, api_key

    def _tenant_script_src(self) -> Optional[str]:
        """Return the absolute URL of the tenant JS bundle on the schedule page."""
        page = Fetcher.get(self.SCHEDULE_URL)
        markup = page.body.decode("utf-8", errors="ignore")
        match = re.search(
            r'<script[^>]*data-type=["\']tenant["\'][^>]*\bsrc=["\']([^"\']+)["\']',
            markup,
        )
        if not match:
            return None
        src = match.group(1)
        if src.startswith("http"):
            return src
        # Resolve a root-relative URL against the schedule page origin.
        return f"https://{self.SCHEDULE_URL.split('/')[2]}{src}"

    # -- API fetch -----------------------------------------------------------

    def _fetch_events(self, event_bucket: str, api_key: str) -> Dict:
        """Fetch all events (screenings) for the bucket from Eventive's API."""
        url = (
            f"{self.API_BASE}/event_buckets/{event_bucket}/events"
            f"?api_key={api_key}"
        )
        body = self._fetch_text(url)
        return json.loads(body)

    @staticmethod
    def _fetch_text(url: str) -> str:
        """GET ``url`` via scrapling's Fetcher and return the response body text."""
        response = Fetcher.get(url)
        return response.body.decode("utf-8", errors="ignore")

    # -- normalisation -------------------------------------------------------

    def _build_films(self, events: List[Dict]) -> List[Dict]:
        """Group Eventive events into per-film dicts the pipeline expects.

        One Eventive event = one screening. Several events may screen the same
        film (e.g. repeat shows of a title under SFS Somerset); those collapse
        into a single film dict with multiple screenings, matching the grain the
        Filmhouse scraper emits.
        """
        films_by_id: Dict[str, Dict] = {}
        for event in events:
            self._merge_event_into_films(event, films_by_id)
        return list(films_by_id.values())

    def _merge_event_into_films(
        self, event: Dict, films_by_id: Dict[str, Dict]
    ) -> None:
        """Add one event's screening(s) to the film dicts for its films."""
        screenings = self._screenings_from_event(event)
        if not screenings:
            return

        themes = self._programme_tags(event)
        venue = self._venue_name(event)
        url = self._event_url(event)

        for film_obj in event.get("films") or []:
            film = films_by_id.get(film_obj["id"])
            if film is None:
                film = self._film_dict(film_obj, themes, venue)
                films_by_id[film_obj["id"]] = film
            # Union programme tags seen across this film's screenings.
            existing_themes = set(film.get("themes") or [])
            film["themes"] = sorted(existing_themes | set(themes))
            film["screenings"].extend(screenings)
            # Make sure each screening links back to its own event page.
            for screening in screenings:
                screening.setdefault("booking_url", url)

    def _film_dict(self, film_obj: Dict, themes: List[str], venue: str) -> Dict:
        """Build a pipeline-shaped film dict from one Eventive film object."""
        details = film_obj.get("details") or {}
        credits = film_obj.get("credits") or {}
        synopsis = self._strip_html(film_obj.get("description") or "")
        return {
            "title": (film_obj.get("name") or "").strip(),
            "url": self._film_url(film_obj),
            "year": str(details.get("year") or ""),
            "duration_mins": self._int_or_default(details.get("runtime")),
            "rating": details.get("rating") or "",
            "genre": details.get("genre") or "",
            "director": credits.get("director") or "",
            "cast": credits.get("cast") or "",
            "language": details.get("language") or "",
            "country": details.get("country") or "",
            "synopsis": synopsis,
            "poster_url": film_obj.get("poster_image") or "",
            "themes": list(themes),
            "tags": [],  # Eventive has no 4K / Q&A / premiere flags
            "venue": venue,
            # SFS-specific calendar-description fields (kept blank where the
            # Eventive source has no analogue of the old sheet's columns).
            "category": themes[0] if themes else "",
            "event_type": "",
            "promo_code": "",
            "member_url": "",
            "source": "sfs",
            "screenings": [],
        }

    def _screenings_from_event(self, event: Dict) -> List[Dict]:
        """Build screening dicts for a dated, non-virtual Eventive event."""
        if event.get("is_virtual") or not event.get("is_dated"):
            return []
        start = self._local_datetime(event.get("start_time"), event.get("timezone"))
        end = self._local_datetime(event.get("end_time"), event.get("timezone"))
        if start is None:
            return []
        if end is None:
            end = start  # defensive; real events always carry end_time
        return [
            {
                "start": start,
                "end": end,
                "booking_url": self._event_url(event),
                "time_str": start.strftime("%-I:%M %p").lstrip("0") or "",
            }
        ]

    def _local_datetime(
        self, iso_utc: Optional[str], tz_name: Optional[str]
    ) -> Optional[datetime]:
        """Convert an Eventive UTC timestamp to a naive local (SGT) datetime.

        Eventive returns ``start_time``/``end_time`` as RFC3339 UTC strings and
        a per-event ``timezone`` (Asia/Singapore for SFS). The Filmhouse scraper
        emits naive local datetimes, so we drop the tzinfo after converting to
        keep both sources comparable downstream.
        """
        if not iso_utc:
            return None
        raw = iso_utc.replace("Z", "+00:00")
        try:
            utc = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=ZoneInfo("UTC"))
        target = ZoneInfo(tz_name) if tz_name else TIMEZONE
        return utc.astimezone(target).replace(tzinfo=None)

    @staticmethod
    def _programme_tags(event: Dict) -> List[str]:
        """Return the event's SFS programme tags (themes for the archive)."""
        names = []
        for tag in event.get("tags") or []:
            name = (tag.get("name") or "").strip()
            if name.startswith(PROGRAMME_TAG_PREFIX):
                names.append(name)
        return sorted(set(names))

    @staticmethod
    def _venue_name(event: Dict) -> str:
        """Return the event's venue name, preferring the structured venue object."""
        venue = event.get("venue")
        if isinstance(venue, dict) and venue.get("name"):
            return venue["name"]
        return (event.get("location") or "").strip() or "Singapore Film Society"

    @staticmethod
    def _event_url(event: Dict) -> str:
        """Permalink to the screening inside the Eventive schedule."""
        event_id = event.get("id") or ""
        return f"{SCHEDULE_URL.rsplit('/', 1)[0]}/schedule/{event_id}"

    @staticmethod
    def _film_url(film_obj: Dict) -> str:
        """Permalink to the film guide entry for this film."""
        film_id = film_obj.get("id") or ""
        return f"{SCHEDULE_URL.rsplit('/', 1)[0]}/films/{film_id}"

    @staticmethod
    def _strip_html(text: str) -> str:
        """Collapse Eventive's rich-text HTML into plain synopsis prose."""
        if not text:
            return ""
        without_tags = re.sub(r"<[^>]+>", " ", text)
        unescaped = html.unescape(without_tags)
        return re.sub(r"\s+", " ", unescaped).strip()

    @staticmethod
    def _int_or_default(value, default: int = 0) -> int:
        """Parse an int that arrives as a string, returning ``default`` if blank."""
        try:
            return int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default