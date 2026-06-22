"""Entry point for the SG Film Calendar sync script.

Scrapes screenings from multiple sources (Filmhouse.sg, Singapore Film Society)
and syncs them to a shared Google Calendar.
"""

import os
import sys

from calendar_sync import CalendarSync
from history import HistoryStore
from scraper import FilmhouseScraper
from sfs_scraper import SFSScraper

HISTORY_CSV = os.environ.get("HISTORY_CSV", "data/films.csv")


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


def _update_history(all_films: list) -> None:
    """Merge scraped films into the historic archive CSV."""
    print(f"\nUpdating film history ({HISTORY_CSV})...")
    store = HistoryStore(HISTORY_CSV)
    stats = store.update(all_films)
    print(f"  → {stats['total']} film-runs tracked ({stats['new']} new)")


def main() -> None:
    """Run the full scrape-and-sync pipeline for all sources."""
    # Scrape all sources
    all_films = []
    all_films.extend(_scrape_filmhouse())
    all_films.extend(_scrape_sfs())

    total_screenings = sum(len(f["screenings"]) for f in all_films)
    print(f"\nTotal: {len(all_films)} items with {total_screenings} screenings")

    if not all_films:
        print("No screenings found. Exiting.")
        return

    # Update the historic archive independently of the calendar sync, so an
    # archive failure doesn't block calendar updates (and vice versa).
    try:
        _update_history(all_films)
    except Exception as exc:  # noqa: BLE001
        print(f"History update failed: {exc}", file=sys.stderr)

    calendar_id = _require_env("GOOGLE_CALENDAR_ID")
    credentials_json = _require_env("GOOGLE_CALENDAR_CREDENTIALS")

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
