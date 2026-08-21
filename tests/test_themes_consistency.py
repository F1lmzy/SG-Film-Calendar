"""Consistency check for the shared `themes` convention across scrapers.

Issue #8: every scraper emits a `themes` list (the curatorial programme /
season) so the archive and calendar can surface it uniformly. This test guards
the Filmhouse scraper's parse path, which fills `themes` in `scrape()` after
parsing; the dict it returns must still carry the key so the shape matches the
other scrapers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scraper import FilmhouseScraper


class _FakeElement:
    def css(self, selector):
        if selector == ".liveeventtitle::text":
            return _Text("A FILM")
        if selector == ".liveeventtitle::attr(href)":
            return _Text("https://filmhouse.sg/film/1/slug")
        return _Many([])


class _Text:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _Many:
    def __init__(self, values):
        self._values = values

    def getall(self):
        return list(self._values)


def test_filmhouse_parse_film_carries_themes_key(monkeypatch):
    scraper = FilmhouseScraper()
    monkeypatch.setattr(scraper, "_extract_duration", lambda el: 120)
    monkeypatch.setattr(scraper, "_extract_metadata", lambda el: ("", "", ""))
    monkeypatch.setattr(scraper, "_extract_credits", lambda el: ("", ""))
    monkeypatch.setattr(scraper, "_extract_synopsis", lambda el: "")
    monkeypatch.setattr(scraper, "_extract_poster", lambda el: "")
    monkeypatch.setattr(scraper, "_extract_tags", lambda el: [])
    monkeypatch.setattr(scraper, "_parse_screenings", lambda el, dur: [])

    film = scraper._parse_film(_FakeElement())

    assert "themes" in film
    assert film["themes"] == []
