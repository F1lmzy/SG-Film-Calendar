"""Scraper for Asian Film Archive (Oldham Theatre) screenings.

AFA lists its current and upcoming screenings at
``https://asianfilmarchive.org/whatson/``. Each listing is a ``mep_events``
article (a custom events post type) rendered by Elementor, carrying:

- the film/programme title (``h5`` inside the card),
- a date + time range in the first icon-list line (e.g. ``August 22, 2026 |
  5:00 PM - 6:40 PM``),
- the venue in the second line (usually ``Oldham Theatre``),
- the poster image, and
- WordPress ``tag-*`` classes on the article that encode the curatorial
  programme (``tag-singapore-shorts``, ``tag-70-years-of-taiyupian``, ...),
  which feed the archive's ``themes`` axis.

Only events whose article carries the ``mep_cat-screening`` category are
treated as screenings; talks (``mep_cat-talks``) and programme placeholders are
skipped. The listing page does not carry synopses or credits, so those fields
are left empty (a separate enrichment step can backfill them, see #7).
"""

import re
from datetime import datetime
from typing import Dict, List, Optional

from scrapling.fetchers import Fetcher

URL = "https://asianfilmarchive.org/whatson/"
DEFAULT_VENUE = "Oldham Theatre"

# Day badges AFA prefixes to titles in its "recently shown" sections. They are
# UI labels, not part of the film title, and are stripped so the title is stable
# regardless of which section an event appears in.
_DAY_LABELS = ("昨天", "今天", "明天", "Yesterday", "Today", "Tomorrow")


class AFAScraper:
    """Scrape AFA / Oldham Theatre screenings from the What's On page."""

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now()

    def scrape(self) -> List[Dict]:
        """Fetch and parse the AFA What's On listings."""
        page = Fetcher.get(URL)
        films: List[Dict] = []
        seen = set()
        for article in page.css("article.mep_events"):
            if not self._is_screening(article):
                continue
            film = self._parse_film(article)
            if not film or not film["screenings"]:
                continue
            # The page sometimes renders one event in two sections; collapse by
            # title + screening start/end so it surfaces once.
            key = (
                film["title"],
                film["screenings"][0]["start"],
                film["screenings"][0]["end"],
            )
            if key in seen:
                continue
            seen.add(key)
            films.append(film)
        return films

    @staticmethod
    def _is_screening(article) -> bool:
        """True when the article is categorised as a film screening."""
        classes = (article.attrib.get("class") or "").split()
        return "mep_cat-screening" in classes

    def _parse_film(self, article) -> Optional[Dict]:
        """Parse one ``mep_events`` article into a film dict."""
        title = self._clean_title((article.css("h5 a::text").get() or "").strip())
        if not title:
            return None

        meta_items = article.css(".elementor-icon-list-text::text").getall()
        meta_items = [item.strip() for item in meta_items if item and item.strip()]

        date_time = meta_items[0] if len(meta_items) > 0 else ""
        venue = meta_items[1] if len(meta_items) > 1 else DEFAULT_VENUE
        screenings = self._parse_screenings(date_time)

        return {
            "title": title,
            "url": (article.css("h5 a::attr(href)").get() or "").strip(),
            "year": self._year(title),
            "duration_mins": 120,  # not stated on the listing page
            "rating": "",  # not stated on the listing page
            "genre": "",  # not stated on the listing page
            "director": "",  # not stated on the listing page
            "cast": "",  # not stated on the listing page
            "language": "",  # not stated on the listing page
            "country": "",  # not stated on the listing page
            "synopsis": "",  # not stated on the listing page
            "poster_url": (article.css("img::attr(src)").get() or "").strip(),
            "themes": self._themes(article),
            "tags": [],
            "venue": venue,
            "screenings": screenings,
            "source": "afa",
        }

    @staticmethod
    def _year(title: str) -> str:
        """Extract a production year from a trailing '(YYYY)' in the title."""
        match = re.search(r"\((\d{4})\)\s*$", title)
        return match.group(1) if match else ""

    @staticmethod
    def _clean_title(title: str) -> str:
        """Strip a leading day badge (e.g. '昨天') from a listing title."""
        title = title.strip()
        for label in _DAY_LABELS:
            if title.startswith(label):
                return title[len(label):].strip()
        return title

    @staticmethod
    def _themes(article) -> List[str]:
        """Derive curatorial themes from the article's WordPress tag classes."""
        classes = (article.attrib.get("class") or "").split()
        themes: List[str] = []
        for cls in classes:
            if not cls.startswith("tag-"):
                continue
            slug = cls[4:]
            # Collapse "...-2026" onto its base programme name.
            slug = re.sub(r"-?\d{4}$", "", slug)
            name = slug.replace("-", " ").title()
            if name and name not in themes:
                themes.append(name)
        return sorted(themes)

    @staticmethod
    def _parse_screenings(date_time: str) -> List[Dict]:
        """Parse a 'Month D, YYYY | H:MM AM - H:MM PM' line into screenings."""
        match = re.match(
            r"([A-Za-z]+ \d{1,2}, \d{4})\s*\|\s*"
            r"(\d{1,2}:\d{2}\s*[AP]M)\s*[-–—]\s*(\d{1,2}:\d{2}\s*[AP]M)",
            date_time,
            re.I,
        )
        if not match:
            return []
        date_str, start_str, end_str = match.groups()
        try:
            date = datetime.strptime(date_str, "%B %d, %Y").date()
            start = datetime.combine(
                date, datetime.strptime(start_str, "%I:%M %p").time()
            )
            end = datetime.combine(
                date, datetime.strptime(end_str, "%I:%M %p").time()
            )
        except ValueError:
            return []
        if end <= start:
            return []
        return [
            {
                "start": start,
                "end": end,
                "booking_url": "",  # filled by the caller's event link if present
                "time_str": f"{start_str} - {end_str}",
            }
        ]
