"""Entry point for the SG Film Calendar sync script.

Scrapes screenings from multiple sources (Filmhouse.sg, Singapore Film Society)
and syncs them to a shared Google Calendar.
"""

import os
import sys

from calendar_sync import CalendarSync
from scraper import FilmhouseScraper
from sfs_scraper import SFSScraper


def _require_env(name: str) -> str:
    """Get a required environment variable or exit."""
    val = os.environ.get(name)
    if not val:
        print(f"Error: {name} environment variable not set", file=sys.stderr)
        sys.exit(1)
    return val


def _scrape_filmhouse() -> list:
    """Scrape Filmhouse.sg and return films list."""
    print("Scraping Filmhouse.sg...")
    scraper = FilmhouseScraper()
    films = scraper.scrape()
    total = sum(len(f["screenings"]) for f in films)
    print(f"  → {len(films)} films with {total} screenings")
    return films


def _scrape_sfs() -> list:
    """Scrape Singapore Film Society and return films list."""
    print("Scraping Singapore Film Society...")
    scraper = SFSScraper()
    films = scraper.scrape()
    total = sum(len(f["screenings"]) for f in films)
    print(f"  → {len(films)} events with {total} screenings")
    return films


def main() -> None:
    """Run the full scrape-and-sync pipeline for all sources."""
    calendar_id = _require_env("GOOGLE_CALENDAR_ID")
    credentials_json = _require_env("GOOGLE_CALENDAR_CREDENTIALS")

    # Scrape all sources
    all_films = []
    all_films.extend(_scrape_filmhouse())
    all_films.extend(_scrape_sfs())

    total_screenings = sum(len(f["screenings"]) for f in all_films)
    print(f"\nTotal: {len(all_films)} items with {total_screenings} screenings")

    if not all_films:
        print("No screenings found. Exiting.")
        return

    print("\nSyncing to Google Calendar...")
    sync = CalendarSync(calendar_id, credentials_json)
    stats = sync.sync_screenings(all_films)

    print(
        f"Done! Created: {stats['created']}, "
        f"Updated: {stats['updated']}, "
        f"Errors: {stats['errors']}"
    )


if __name__ == "__main__":
    main()
