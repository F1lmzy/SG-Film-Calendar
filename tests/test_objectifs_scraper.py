import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from objectifs_scraper import ObjectifsScraper


def test_no_dated_schedule_yet():
    """Objectifs currently publishes no dated screening schedule."""
    assert ObjectifsScraper._parse_screenings(None) == []


def test_scrape_returns_empty_while_no_schedule(monkeypatch):
    import objectifs_scraper

    class FakeResponse:
        body = b"<html></html>"

    class FakeFetcher:
        @staticmethod
        def get(url):
            assert url == objectifs_scraper.URL
            return FakeResponse()

    monkeypatch.setattr(objectifs_scraper, "Fetcher", FakeFetcher)
    assert ObjectifsScraper().scrape() == []
