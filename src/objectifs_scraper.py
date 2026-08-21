"""Scraper for Objectifs – Centre for Photography & Film.

Objectifs runs a year-round Southeast-Asian short-film programme at
``https://www.objectifs.com.sg/objectifs-cinema-now-showing/``. As of the time
this scraper was written, that page describes the current exhibition
("Objectifs Cinema: Now Showing") and its programme strands, but does **not**
publish a per-screening schedule: there are no dated listings with start times,
venues, or ticket links — the films are described as "screened over the course
of this exhibition" without a machine-readable timetable.

Because the pipeline (calendar sync + history archive) is keyed on dated
screenings, there is nothing to emit yet. This scraper keeps the standard
``scrape() -> List[Dict]`` interface and returns an empty list until Objectifs
publishes a schedule; revisit when they add a dated listing (see issue #3).
"""

from datetime import datetime
from typing import Dict, List, Optional

from scrapling.fetchers import Fetcher

URL = "https://www.objectifs.com.sg/objectifs-cinema-now-showing/"


class ObjectifsScraper:
    """Scrape Objectifs' Now Showing page for dated film screenings."""

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now()

    def scrape(self) -> List[Dict]:
        """Return dated screenings, or an empty list while none are published."""
        page = Fetcher.get(URL)
        return self._parse_screenings(page)

    @staticmethod
    def _parse_screenings(page) -> List[Dict]:
        """Parse dated screening entries from the page.

        The current page carries no dated schedule, so this returns ``[]``.
        When Objectifs adds one, extend this to map their listing markup onto
        the standard film/``screenings`` shape used by the other scrapers.
        """
        return []
