from datetime import datetime

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afa_scraper import AFAScraper


class FakeArticle:
    """Minimal stand-in for a scrapling element with the selectors we use."""

    def __init__(self, classes, title, url, poster, meta_items):
        self.attrib = {"class": classes}
        self._title = title
        self._url = url
        self._poster = poster
        self._meta_items = meta_items

    def css(self, selector):
        if selector == "h5 a::text":
            return _One(self._title)
        if selector == "h5 a::attr(href)":
            return _One(self._url)
        if selector == ".elementor-icon-list-text::text":
            return _Many(self._meta_items)
        if selector == "img::attr(src)":
            return _One(self._poster)
        return _Many([])


class _One:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _Many:
    def __init__(self, values):
        self._values = values

    def getall(self):
        return list(self._values)


SCREENING_ARTICLE = FakeArticle(
    classes=(
        "mep_events tag-singapore-shorts tag-singapore-shorts-2026 "
        "mep_cat-screening mep_org-oldham-theatre"
    ),
    title="Singapore Shorts \u201926 \u2013 Official Selection 3",
    url="https://asianfilmarchive.org/event-calendar/singapore-shorts-26-selection-3/",
    poster="https://asianfilmarchive.org/wp-content/uploads/2026/07/OS3-768x512.jpg",
    meta_items=["August 22, 2026 | 5:00 PM - 6:40 PM", "Oldham Theatre"],
)

TALK_ARTICLE = FakeArticle(
    classes="mep_events mep_cat-talks mep_org-oldham-theatre",
    title="[TALK] The Birth of a Nation on Screen",
    url="https://asianfilmarchive.org/event-calendar/birth-of-a-nation-on-screen-talk/",
    poster="",
    meta_items=["August 23, 2026 | 4:00 PM - 5:30 PM", "Oldham Theatre"],
)


def test_is_screening():
    assert AFAScraper._is_screening(SCREENING_ARTICLE) is True
    assert AFAScraper._is_screening(TALK_ARTICLE) is False


def test_year_from_title():
    assert AFAScraper._year("Past Present (2013)") == "2013"
    assert AFAScraper._year("Singapore Shorts \u201926 \u2013 Official Selection 3") == ""


def test_clean_title_strips_day_badge():
    assert AFAScraper._clean_title("\u6628\u5929 Past Present (2013)") == "Past Present (2013)"
    assert AFAScraper._clean_title("Today Some Film") == "Some Film"
    assert AFAScraper._clean_title("Ordinary Film") == "Ordinary Film"


def test_themes_from_tag_classes():
    themes = AFAScraper._themes(SCREENING_ARTICLE)
    assert themes == ["Singapore Shorts"]


def test_parse_screenings_single_date_range():
    screenings = AFAScraper._parse_screenings("August 22, 2026 | 5:00 PM - 6:40 PM")
    assert len(screenings) == 1
    assert screenings[0]["start"] == datetime(2026, 8, 22, 17, 0)
    assert screenings[0]["end"] == datetime(2026, 8, 22, 18, 40)


def test_parse_screenings_bad_input():
    assert AFAScraper._parse_screenings("") == []
    assert AFAScraper._parse_screenings("No schedule published") == []


def test_parse_film_full_shape():
    film = AFAScraper()._parse_film(SCREENING_ARTICLE)
    assert film["source"] == "afa"
    assert film["title"] == "Singapore Shorts \u201926 \u2013 Official Selection 3"
    assert film["venue"] == "Oldham Theatre"
    assert film["themes"] == ["Singapore Shorts"]
    assert film["poster_url"].endswith("OS3-768x512.jpg")
    assert len(film["screenings"]) == 1


def test_parse_film_talk_is_not_a_screening():
    # _parse_film assumes the caller already filtered, but should still parse;
    # the scrape() loop is what skips talks via _is_screening.
    assert AFAScraper()._parse_film(TALK_ARTICLE) is not None
