from datetime import datetime

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nlb_scraper import NLBScraper


RAYA_EVENT = {
    "id": 5914353,
    "title": '"Raya and The Last Dragon" Film Screening | All Things Singapore 2026',
    "url": "https://nlb.libcal.com/event/5914353",
    "startdt": "2026-08-22 19:00:00",
    "enddt": "2026-08-22 20:50:00",
    "all_day": False,
    "location": "CAL - National Library Building - The Plaza (Level 1)",
    "featured_image": "https://example.com/poster.jpg",
    "categories_arr": [
        {"cat_id": 45297, "name": "Areas of Interest > Art & Creativity"},
        {"cat_id": 45313, "name": "Event Type > Performance"},
        {"cat_id": 45305, "name": "Language > English"},
    ],
    "description": (
        "<p>Film Title: Raya &amp; the Last Dragon</p>"
        "<p>Synopsis: Long ago, in the fantasy world of Kumandra, humans and "
        "dragons lived together in harmony.</p>"
        "<p>Important Note: Attendees are to bring their own smartphone.</p>"
    ),
}

GENERIC_EVENT = {
    "id": 5911211,
    "title": "Movie Screening @ Queenstown Library",
    "url": "https://nlb.libcal.com/event/5911211",
    "startdt": "2026-08-22 15:00:00",
    "enddt": "2026-08-22 17:00:00",
    "all_day": False,
    "location": "Queenstown Library - Programme Zone (Level 1)",
    "featured_image": "",
    "categories_arr": [
        {"cat_id": 45326, "name": "Areas of Interest > Health"},
        {"cat_id": 45582, "name": "Event Type > Others"},
        {"cat_id": 45305, "name": "Language > English"},
    ],
    "description": "<p>Watch a Movie at the Library.</p>",
}

BIG_PICTURE_EVENT = {
    "id": 5910672,
    "title": "The Big Picture - Fortnightly Film Screening (23 July)",
    "url": "https://nlb.libcal.com/event/5910672",
    "startdt": "2026-07-23 19:30:00",
    "enddt": "2026-07-23 21:30:00",
    "all_day": False,
    "location": "Central Arts Library",
    "featured_image": "",
    "categories_arr": [
        {"cat_id": 45313, "name": "Event Type > Performance"},
    ],
    "description": (
        "This Month's Theme: A Harried Homecoming "
        "Film Synopsis: In this tender drama film, a woman does her best to "
        "raise her son up in a confined space. Advisory: PG."
    ),
}

NON_FILM_EVENT = {
    "id": 5911812,
    "title": "Spark!Lab | Punggol Library",
    "url": "https://nlb.libcal.com/event/5911812",
    "startdt": "2026-08-01 10:00:00",
    "enddt": "2026-08-01 11:00:00",
    "location": "Punggol Library",
    "description": "Calling all children to tinker!",
}


def test_is_film_detects_screenings():
    assert NLBScraper._is_film(RAYA_EVENT) is True
    assert NLBScraper._is_film(GENERIC_EVENT) is True
    assert NLBScraper._is_film(BIG_PICTURE_EVENT) is True
    assert NLBScraper._is_film(NON_FILM_EVENT) is False


def test_film_title_prefers_explicit_field():
    desc = NLBScraper._plain_text(RAYA_EVENT["description"])
    assert NLBScraper._film_title(RAYA_EVENT, desc) == "Raya & the Last Dragon"


def test_film_title_falls_back_to_event_title():
    desc = NLBScraper._plain_text(GENERIC_EVENT["description"])
    # No "Film Title:" and no quoted segment, so the event title is kept.
    assert NLBScraper._film_title(GENERIC_EVENT, desc) == "Movie Screening @ Queenstown Library"


def test_film_title_big_picture_series():
    desc = NLBScraper._plain_text(BIG_PICTURE_EVENT["description"])
    title = NLBScraper._film_title(BIG_PICTURE_EVENT, desc)
    assert title.startswith("The Big Picture")


def test_themes_programme_and_monthly():
    desc = NLBScraper._plain_text(RAYA_EVENT["description"])
    assert NLBScraper._themes(RAYA_EVENT, desc) == [
        "All Things Singapore 2026",
        "NLB Film Screenings",
    ]

    big_desc = NLBScraper._plain_text(BIG_PICTURE_EVENT["description"])
    themes = NLBScraper._themes(BIG_PICTURE_EVENT, big_desc)
    assert "NLB Film Screenings" in themes
    assert "The Big Picture" in themes
    assert "A Harried Homecoming" in themes


def test_synopsis_and_rating():
    desc = NLBScraper._plain_text(RAYA_EVENT["description"])
    assert NLBScraper._synopsis(desc).startswith("Long ago")

    big_desc = NLBScraper._plain_text(BIG_PICTURE_EVENT["description"])
    assert NLBScraper._rating(big_desc) == "PG"


def test_language_from_categories():
    assert NLBScraper._language(RAYA_EVENT) == "English"


def test_parse_screenings_uses_timestamps():
    scraper = NLBScraper()
    screenings = scraper._parse_screenings(RAYA_EVENT)
    assert len(screenings) == 1
    assert screenings[0]["start"] == datetime(2026, 8, 22, 19, 0)
    assert screenings[0]["end"] == datetime(2026, 8, 22, 20, 50)
    assert screenings[0]["booking_url"] == RAYA_EVENT["url"]


def test_parse_film_full_shape():
    scraper = NLBScraper()
    film = scraper._parse_film(RAYA_EVENT)
    assert film["source"] == "nlb"
    assert film["title"] == "Raya & the Last Dragon"
    assert film["themes"] == ["All Things Singapore 2026", "NLB Film Screenings"]
    assert film["venue"] == "CAL - National Library Building - The Plaza (Level 1)"
    assert film["poster_url"] == "https://example.com/poster.jpg"
    assert len(film["screenings"]) == 1


def test_parse_film_skips_non_film():
    scraper = NLBScraper()
    assert scraper._parse_film(NON_FILM_EVENT) is None
