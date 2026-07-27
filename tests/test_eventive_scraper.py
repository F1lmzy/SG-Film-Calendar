"""Tests for the Eventive-based Singapore Film Society scraper.

Uses fixture API payloads (no network) so the tests are deterministic.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import eventive_scraper
from eventive_scraper import EventiveScraper

TENANT_JS = (
    'TENANT = {"endpoint":"https://api.eventive.org/",'
    '"event_bucket":"BUCKET123","api_key":"KEY456"};\n'
)

SCHEDULE_HTML = (
    '<html><head>'
    '<script data-type="global" src="/global.abc.js"></script>'
    '<script data-type="tenant" src="/singaporefilmsociety.tenant.js"></script>'
    '</head><body><div id="app"></div></body></html>'
)


def _venue(name="GV Cineleisure Hall 6 (SFS Somerset)"):
    return {
        "id": "vid1",
        "name": name,
        "short_name": "SFS Somerset",
        "address": "8 Grange Road",
    }


def _film(
    fid="film1",
    name="Blue Velvet",
    year="1986",
    runtime="120",
    rating="M18",
    language="English",
    country="United States",
    genre="Crime, Mystery, Thriller",
):
    return {
        "id": fid,
        "name": name,
        "description": "<p>A <em>young</em> mystery...</p>",
        "poster_image": f"https://static-a.eventive.org/{fid}.jpg?w=300",
        "details": {
            "year": year,
            "runtime": runtime,
            "rating": rating,
            "language": language,
            "country": country,
            "genre": genre,
            "subtitle_language": "English",
        },
        "credits": {
            "director": "David Lynch",
            "cast": "Kyle MacLachlan, Isabella Rossellini",
        },
        "tags": [],
    }


def _event(
    eid="ev1",
    film=None,
    start="2026-07-22T11:30:00.000Z",
    end="2026-07-22T13:30:00.000Z",
    tags=None,
    timezone="Asia/Singapore",
    venue=None,
    is_virtual=False,
    is_dated=True,
):
    return {
        "id": eid,
        "name": "SFS Somerset: Blue Velvet",
        "timezone": timezone,
        "start_time": start,
        "end_time": end,
        "venue": venue or _venue(),
        "location": "GV Cineleisure Hall 6 (SFS Somerset)",
        "is_dated": is_dated,
        "is_virtual": is_virtual,
        "tags": tags if tags is not None else [
            {"id": "t1", "name": "SFS Somerset", "visible": True},
            {"id": "t2", "name": "$6 Off for Members", "visible": True},
        ],
        "films": [film or _film()],
    }


class _FakeResponse:
    def __init__(self, body_bytes):
        self.body = body_bytes
        self.status = 200


def _patch_fetch(monkeypatch, *, html=SCHEDULE_HTML, tenant=TENANT_JS, api_events=None):
    """Record all URLs fetched and return canned bodies: the schedule page HTML,
    the tenant JS, and the JSON API payload."""

    calls = []

    def fake_get(url):
        calls.append(url)
        if url.endswith("/schedule"):
            return _FakeResponse(html.encode())
        if url.endswith("tenant.js") or url.endswith(".js") and "tenant" in url:
            return _FakeResponse(tenant.encode())
        if "/events" in url:
            payload = api_events if api_events is not None else {"events": []}
            import json
            return _FakeResponse(json.dumps(payload).encode())
        return _FakeResponse(b"{}")

    monkeypatch.setattr(eventive_scraper, "Fetcher", type("F", (), {"get": staticmethod(fake_get)}))
    return calls


def test_credentials_discovered_from_tenant_bundle(monkeypatch):
    calls = _patch_fetch(monkeypatch, api_events={"events": []})
    EventiveScraper().scrape()

    # schedule page -> tenant JS (relative) -> API call with discovered creds
    assert calls[0].endswith("/schedule")
    assert any("tenant.js" in c for c in calls)
    api_call = next(c for c in calls if "/events" in c)
    assert "event_buckets/BUCKET123" in api_call
    assert "api_key=KEY456" in api_call


def test_falls_back_to_default_credentials_when_tenant_missing(monkeypatch):
    # No tenant script at all on the schedule page.
    html = "<html><script data-type='global' src='/g.js'></script></html>"
    calls = _patch_fetch(monkeypatch, html=html, api_events={"events": []})
    EventiveScraper().scrape()

    api_call = next(c for c in calls if "/events" in c)
    assert EventiveScraper.DEFAULT_EVENT_BUCKET in api_call
    assert EventiveScraper.DEFAULT_API_KEY in api_call


def test_utc_timestamps_converted_to_naive_sgt():
    sc = EventiveScraper()
    dt = sc._local_datetime("2026-07-22T11:30:00.000Z", "Asia/Singapore")
    # 11:30 UTC == 19:30 SGT, naive
    assert dt == datetime(2026, 7, 22, 19, 30)
    assert dt.tzinfo is None


def test_event_becomes_screening_with_correct_time(monkeypatch):
    event = _event()
    _patch_fetch(monkeypatch, api_events={"events": [event]})
    [film] = EventiveScraper().scrape()

    assert film["title"] == "Blue Velvet"
    [screening] = film["screenings"]
    assert screening["start"] == datetime(2026, 7, 22, 19, 30)
    assert screening["end"] == datetime(2026, 7, 22, 21, 30)
    assert screening["booking_url"].endswith("/schedule/ev1")


def test_repeated_screenings_of_same_film_group_into_one_dict(monkeypatch):
    film = _film()
    e1 = _event("ev1", film=film, start="2026-07-22T11:30:00.000Z",
                end="2026-07-22T13:30:00.000Z")
    e2 = _event("ev2", film=film, start="2026-07-29T11:30:00.000Z",
                end="2026-07-29T13:30:00.000Z")
    _patch_fetch(monkeypatch, api_events={"events": [e1, e2]})

    films = EventiveScraper().scrape()
    assert len(films) == 1
    assert [s["start"] for s in films[0]["screenings"]] == [
        datetime(2026, 7, 22, 19, 30),
        datetime(2026, 7, 29, 19, 30),
    ]


def test_programme_tags_filter_to_sfs_prefix_and_exclude_pricing_tags(monkeypatch):
    event = _event(tags=[
        {"name": "SFS Somerset", "visible": True},
        {"name": "SFS Showcase", "visible": True},
        {"name": "$6 Off for Members", "visible": True},
        {"name": "Free for Members", "visible": True},
    ])
    _patch_fetch(monkeypatch, api_events={"events": [event]})
    [film] = EventiveScraper().scrape()

    assert film["themes"] == ["SFS Showcase", "SFS Somerset"]  # sorted, pricing excluded
    assert film["category"] == "SFS Showcase"  # first theme


def test_film_dict_carries_structured_metadata(monkeypatch):
    _patch_fetch(monkeypatch, api_events={"events": [_event()]})
    [film] = EventiveScraper().scrape()

    assert film["year"] == "1986"            # production year, not screening year
    assert film["duration_mins"] == 120
    assert film["rating"] == "M18"
    assert film["director"] == "David Lynch"
    assert film["cast"] == "Kyle MacLachlan, Isabella Rossellini"
    assert film["language"] == "English"
    assert film["country"] == "United States"
    assert film["genre"] == "Crime, Mystery, Thriller"
    assert film["poster_url"].startswith("https://static-a.eventive.org/film1.jpg")
    assert "young mystery" in film["synopsis"].lower()  # HTML stripped
    assert film["venue"] == "GV Cineleisure Hall 6 (SFS Somerset)"
    assert film["source"] == "sfs"
    assert film["url"].endswith("/films/film1")


def test_virtual_or_undated_events_are_skipped(monkeypatch):
    virtual = _event("evv", is_virtual=True)
    undated = _event("evu", is_dated=False, start=None, end=None)
    normal = _event("evn")
    _patch_fetch(monkeypatch, api_events={"events": [virtual, undated, normal]})

    films = EventiveScraper().scrape()
    assert len(films) == 1
    assert films[0]["screenings"][0]["booking_url"].endswith("/schedule/evn")


def test_event_url_and_film_url_endpoints():
    ev = _event("ev9")
    fl = _film("film9")
    assert EventiveScraper._event_url(ev).endswith("/schedule/ev9")
    assert EventiveScraper._film_url(fl).endswith("/films/film9")