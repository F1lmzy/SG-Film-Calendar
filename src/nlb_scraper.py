"""Scraper for NLB (National Library Board) film screenings via LibCal.

NLB publishes its library programmes — including curated film screenings such
as the "The Big Picture" series and "All Things Singapore" — through
Springshare LibCal at ``https://nlb.libcal.com``. The public calendar loads its
events from a JSON endpoint (the same one the site's fullcalendar widget calls),
so this scraper reads that endpoint directly instead of parsing the calendar's
HTML shell.

Not every NLB event is a film, so the scraper filters to events whose title or
description marks them as a film/movie screening. Rich events (e.g. the open-air
"All Things Singapore" screenings) carry the film title, synopsis, and rating
inside the description prose; those are extracted best-effort. Generic
screenings (e.g. "Movie Screening @ Queenstown Library") surface with a title
and venue but no film metadata, because the source does not state it.
"""

import html
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

# Public LibCal AJAX endpoint backing the "Discover More Happenings" calendar.
_API_URL = "https://nlb.libcal.com/ajax/calendar/list"
_DISCOVER_CAL_ID = 11498

# Default curatorial theme for every NLB film screening (see issue #8). More
# specific themes (a programme, a monthly "Big Picture" theme) are appended.
BASE_THEME = "NLB Film Screenings"
DEFAULT_VENUE = "National Library Board"

# Look-ahead window: the LibCal list endpoint returns a rolling window around
# the requested date, so query several offsets and dedupe to cover ~3 months of
# upcoming screenings.
_LOOKAHEAD_DAYS = (0, 30, 60)

# Field labels recognised in LibCal description prose, used to bound the value
# of one labelled field when the next one starts (the prose often runs the
# fields together without line breaks).
_LABELS = (
    "film title",
    "film synopsis",
    "synopsis",
    "this month's theme",
    "advisory",
    "about",
    "about the programme",
    "important note",
)


class NLBScraper:
    """Scrape NLB film screenings from LibCal's public events JSON."""

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now()

    def scrape(self) -> List[Dict]:
        """Fetch and parse all upcoming NLB film screenings."""
        events = self._fetch_upcoming_events()
        films: List[Dict] = []
        for event in events:
            film = self._parse_film(event)
            if film and film["screenings"]:
                films.append(film)
        return films

    # -- fetching ------------------------------------------------------------

    def _fetch_upcoming_events(self) -> List[Dict]:
        """Collect events across the look-ahead window, deduped by event id."""
        by_id: Dict[str, Dict] = {}
        for offset in _LOOKAHEAD_DAYS:
            day = self.reference_date + timedelta(days=offset)
            for event in self._fetch_events_on(day.strftime("%Y-%m-%d")):
                by_id[event["id"]] = event
        return list(by_id.values())

    def _fetch_events_on(self, date_str: str) -> List[Dict]:
        """Return every page of events for a given reference date."""
        events: List[Dict] = []
        page = 1
        while True:
            data = self._fetch_json(date_str, page)
            results = data.get("results") or []
            events.extend(results)
            total = int(data.get("total_results") or 0)
            per_page = int(data.get("perpage") or len(results) or 1)
            if not results or page * per_page >= total:
                break
            page += 1
        return events

    @staticmethod
    def _fetch_json(date_str: str, page: int) -> Dict:
        """GET one page of the LibCal list endpoint and decode its JSON."""
        url = (
            f"{_API_URL}?c={_DISCOVER_CAL_ID}&date={date_str}"
            f"&perpage=200&page={page}"
        )
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # -- filtering -----------------------------------------------------------

    @staticmethod
    def _is_film(event: Dict) -> bool:
        """True when an event's title/description marks it as a screening."""
        text = f"{event.get('title', '')} {event.get('description', '')}"
        return bool(re.search(r"\b(film|movie)\s+screening\b", text, re.I))

    # -- parsing -------------------------------------------------------------

    def _parse_film(self, event: Dict) -> Optional[Dict]:
        """Parse a LibCal event into the pipeline's film dict."""
        if not self._is_film(event):
            return None
        screenings = self._parse_screenings(event)
        if not screenings:
            return None

        description = self._plain_text(event.get("description") or "")
        return {
            "title": self._film_title(event, description),
            "url": event.get("url") or "",
            "year": "",  # not stated in the NLB feed
            "duration_mins": self._duration_mins(event),
            "rating": self._rating(description),
            "genre": "",  # not stated in the NLB feed
            "director": "",  # not stated in the NLB feed
            "cast": "",  # not stated in the NLB feed
            "language": self._language(event),
            "country": "",  # not stated in the NLB feed
            "synopsis": self._synopsis(description),
            "poster_url": event.get("featured_image") or "",
            "themes": self._themes(event, description),
            "tags": [],  # NLB publishes no 4K / Q&A / premiere flags
            "venue": (event.get("location") or "").strip() or DEFAULT_VENUE,
            "screenings": screenings,
            "source": "nlb",
        }

    @staticmethod
    def _film_title(event: Dict, description: str) -> str:
        """Best-effort film title from the event title and description."""
        title = (event.get("title") or "").strip()

        # Explicit "Film Title: X" in the description prose wins.
        field = NLBScraper._field(description, "film title")
        if field:
            return field

        # Quoted title ahead of "Film/Movie Screening" (e.g. "Raya... ").
        match = re.search(r'"([^"]+)"\s*(?:film|movie)\s+screening', title, re.I)
        if match:
            return match.group(1).strip()

        # Otherwise fall back to the event title, dropping the trailing
        # programme segment and any parenthesised date (which would otherwise
        # make the title unstable across the series' runs). The "Film/Movie
        # Screening" marker is kept as the best available identifier.
        cleaned = re.sub(r"\|.*$", "", title)
        cleaned = re.sub(r"\([^)]*\d{1,2}\s+\w+\)\s*$", "", cleaned)
        cleaned = cleaned.strip(" -–")
        return cleaned or title

    @staticmethod
    def _themes(event: Dict, description: str) -> List[str]:
        """Curatorial themes: the base NLB theme plus any programme/season."""
        themes = [BASE_THEME]
        title = (event.get("title") or "").strip()

        # A trailing "| Programme" segment names the programme/festival.
        match = re.search(r"\|\s*([^|]+)$", title)
        if match:
            themes.append(match.group(1).strip())

        # The Big Picture publishes a monthly theme in the description prose.
        monthly = NLBScraper._field(description, "this month's theme")
        if monthly:
            themes.append(monthly)

        if "big picture" in title.lower():
            themes.append("The Big Picture")

        return sorted(set(t for t in themes if t))

    @staticmethod
    def _synopsis(description: str) -> str:
        """Extract the film synopsis from the description prose."""
        return NLBScraper._field(description, "synopsis", "film synopsis")

    @staticmethod
    def _rating(description: str) -> str:
        """Extract the advisory rating (e.g. 'PG') from the description."""
        match = re.search(r"advisory\s*:\s*(\S+)", description, re.I)
        return match.group(1).strip(".,;") if match else ""

    @staticmethod
    def _field(description: str, *labels: str) -> str:
        """Return the value of the first matching 'Label: ...' field.

        The value runs until the next recognised label (or end of text), so
        fields that run together in one prose block are split correctly.
        """
        label_alt = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_alt})\s*:\s*", description, re.I)
        if not match:
            return ""
        start = match.end()
        all_labels = "|".join(re.escape(label) for label in _LABELS)
        next_match = re.search(rf"\s+(?:{all_labels})\s*:", description[start:], re.I)
        end = start + next_match.start() if next_match else len(description)
        return re.sub(r"\s+", " ", description[start:end]).strip()

    @staticmethod
    def _language(event: Dict) -> str:
        """Return the event's language from its 'Language > X' category."""
        for category in event.get("categories_arr") or []:
            name = (category.get("name") or "").strip()
            if name.lower().startswith("language > "):
                return name.split(">", 1)[1].strip()
        return ""

    def _duration_mins(self, event: Dict) -> int:
        """Duration from start/end timestamps, defaulting to 120 minutes."""
        start = self._parse_dt(event.get("startdt"))
        end = self._parse_dt(event.get("enddt"))
        if start and end and end > start:
            return int((end - start).total_seconds() // 60)
        return 120

    def _parse_screenings(self, event: Dict) -> List[Dict]:
        """Build the screening entry from the event's start/end timestamps."""
        start = self._parse_dt(event.get("startdt"))
        if start is None:
            return []
        end = self._parse_dt(event.get("enddt")) or (start + timedelta(hours=2))
        if end <= start:
            end = start + timedelta(hours=2)
        return [
            {
                "start": start,
                "end": end,
                "booking_url": event.get("url") or "",
                "time_str": start.strftime("%-I:%M %p").lstrip("0") or "",
            }
        ]

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        """Parse a LibCal timestamp like '2026-08-22 19:00:00'."""
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    @staticmethod
    def _plain_text(markup: str) -> str:
        """Collapse HTML into plain text with a newline kept between blocks."""
        text = re.sub(r"<(br|/p|/div|/li)>", "\n", markup, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return html.unescape(text)
