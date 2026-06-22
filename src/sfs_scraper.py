"""Scraper for Singapore Film Society events from their public Google Sheet."""

import csv
import io
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.request import Request, urlopen


class SFSScraper:
    """Scrape film/event data from Singapore Film Society's public Google Sheet.

    The SFS website embeds a custom widget that reads from a published Google Sheet
    CSV export. This scraper reads the same CSV directly.
    """

    CSV_URL = (
        "https://docs.google.com/spreadsheets/d/e/"
        "2PACX-1vTvhqremXNqIVCB3dv-pVLe5Tn3c1mrdY-83fqXt1c_WUEkQ9w0AazTAA457205oHM4p_R0X7uYjxdl"
        "/pub?gid=0&single=true&output=csv"
    )
    DEFAULT_LOCATION = "Singapore Film Society"

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now()

    def scrape(self) -> List[Dict]:
        """Fetch and parse all SFS events from the Google Sheet CSV."""
        text = self._fetch_csv()
        reader = csv.DictReader(io.StringIO(text))

        films: List[Dict] = []
        for row in reader:
            film = self._parse_event(row)
            if film and film["screenings"]:
                films.append(film)

        return films

    def _fetch_csv(self) -> str:
        """Download the published CSV."""
        req = Request(self.CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req) as resp:
            return resp.read().decode("utf-8-sig")

    def _parse_event(self, row: Dict) -> Optional[Dict]:
        """Parse a single row from the CSV into a film-like dict."""
        title = (row.get("Title") or "").strip()
        if not title:
            return None

        start_date = self._parse_date(row.get("Start Date", ""))
        end_date = self._parse_date(row.get("End Date", ""))
        if not start_date:
            return None

        venue = (row.get("Venue") or "").strip()
        category = (row.get("Category") or "").strip()
        event_type = (row.get("Type") or "").strip()
        time_str = (row.get("Time") or "").strip()
        public_url = (row.get("Public URL") or "").strip()
        member_url = (row.get("Member URL") or "").strip()
        promo_code = (row.get("Code") or "").strip()

        screenings = self._parse_screenings(start_date, end_date, time_str, public_url)

        if not screenings:
            return None

        return {
            "title": title,
            "url": public_url,
            "year": str(start_date.year),
            "duration_mins": 120,  # default; SFS sheet doesn't include duration
            "rating": "",
            "genre": category,
            "director": "",
            "cast": "",
            "venue": venue or self.DEFAULT_LOCATION,
            "category": category,
            "event_type": event_type,
            "promo_code": promo_code,
            "member_url": member_url,
            "screenings": screenings,
            "source": "sfs",
        }

    @staticmethod
    def _parse_date(date_str: str) -> Optional[date]:
        """Parse various date formats used in the SFS sheet."""
        date_str = date_str.strip()
        if not date_str or date_str.upper() == "NA" or date_str.upper() == "N/A":
            return None

        # Try formats like "24 Jun 2026", "24 June 2026", "12-June-2026"
        for fmt in ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        # Try m/d/yyyy (e.g. "5/11/2025")
        parts = date_str.split("/")
        if len(parts) == 3:
            try:
                return date(int(parts[2]), int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass

        return None

    @staticmethod
    def _parse_time(time_str: str) -> Optional[datetime.time]:
        """Parse time strings like '7.00pm', '7:00:00 pm', '1.30pm'."""
        time_str = time_str.strip()
        if not time_str or time_str.upper() == "NA" or time_str.upper() == "N/A":
            return None

        # Normalise "." to ":" for consistency
        normalised = time_str.replace(".", ":")

        # Try HH:MM:SS am/pm, HH:MM am/pm, HH am/pm
        for fmt in ("%I:%M:%S %p", "%I:%M %p", "%I %p"):
            try:
                return datetime.strptime(normalised, fmt).time()
            except ValueError:
                continue

        return None

    def _parse_screenings(
        self,
        start_date: date,
        end_date: Optional[date],
        time_str: str,
        booking_url: str,
    ) -> List[Dict]:
        """Build screening entries from date / time info."""
        end_date = end_date or start_date
        parsed_time = self._parse_time(time_str)
        is_multi_day = start_date != end_date

        if is_multi_day and not parsed_time:
            # Multi-day festival / season without a specific time
            # Use exclusive end (start of day after end_date) for clean calendar display
            start_dt = datetime.combine(start_date, datetime.min.time())
            end_dt = datetime.combine(
                end_date + timedelta(days=1), datetime.min.time()
            )
            return [
                {
                    "start": start_dt,
                    "end": end_dt,
                    "booking_url": booking_url,
                    "time_str": "Various",
                }
            ]

        if parsed_time:
            start_dt = datetime.combine(start_date, parsed_time)
            end_dt = start_dt + timedelta(hours=2)  # assume ~2 hours
            return [
                {
                    "start": start_dt,
                    "end": end_dt,
                    "booking_url": booking_url,
                    "time_str": time_str,
                }
            ]

        # Single day, no time → all-day placeholder
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)  # exclusive end
        return [
            {
                "start": start_dt,
                "end": end_dt,
                "booking_url": booking_url,
                "time_str": "",
            }
        ]
