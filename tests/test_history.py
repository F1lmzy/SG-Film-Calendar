"""Tests for the historic archive (merge-upsert of film-runs from all sources)."""

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from history import HistoryStore


def _load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _filmhouse_film(title="BLUE VELVET", year="1986", themes=None, tags=None,
                    screenings=None, poster="https://fh/posters/bv.png"):
    """A film dict in the shape the enriched Filmhouse scraper emits."""
    return {
        "title": title,
        "year": year,
        "director": "David Lynch",
        "cast": "Kyle MacLachlan",
        "genre": "Mystery",
        "rating": "(M18)",
        "duration_mins": 120,
        "language": "English",
        "country": "United States",
        "synopsis": "In English with English subtitles. A American classic.",
        "poster_url": poster,
        "themes": themes or ["Pink Screen"],
        "tags": tags or [],
        "venue": "",
        "source": "filmhouse",
        "screenings": screenings
        or [
            {"start": datetime(2026, 6, 24, 19, 30),
             "end": datetime(2026, 6, 24, 21, 30), "time_str": "7:30 PM"},
        ],
    }


def _sfs_film(title="BLUE VELVET", category="SFS Somerset",
              poster="https://cdn.peatix.com/event/5080329/cover-x.png",
              screenings=None):
    """A film dict in the shape the (advanced) SFS scraper emits once a
    Somerset bundle has been expanded into its component films."""
    return {
        "title": title,
        "year": "2026",
        "director": "",
        "cast": "",
        "genre": category,
        "rating": "",
        "duration_mins": 120,
        "language": "",
        "country": "",
        "synopsis": "",
        "poster_url": poster,
        "themes": [category],
        "tags": [],
        "venue": "Golden Village Cineleisure, Hall 6",
        "category": category,
        "source": "sfs",
        "screenings": screenings
        or [
            {"start": datetime(2026, 7, 17, 19, 30),
             "end": datetime(2026, 7, 17, 21, 30), "time_str": "7.30pm"},
        ],
    }


def test_sfs_film_archives_with_same_fields_as_filmhouse(tmp_path):
    """SFS films land in the archive with themes, poster, venue and discrete
    screening dates — the same shape as a Filmhouse film-run row."""
    path = str(tmp_path / "films.csv")
    store = HistoryStore(path)
    stats = store.update([_sfs_film()])

    assert stats == {"total": 1, "new": 1}
    [row] = _load(path)
    assert row["source"] == "sfs"
    assert row["themes"] == "SFS Somerset"          # category → theme
    assert row["poster_url"].startswith("https://cdn.peatix.com")
    assert row["venues"] == "Golden Village Cineleisure, Hall 6"
    # discrete screening → one timestamp, count 1
    assert row["screening_count"] == "1"
    assert row["screening_dates"] == "2026-07-17T19:30:00"
    assert row["first_screening"] == row["last_screening"] == "2026-07-17T19:30:00"
    # metadata the SFS sheet does not carry stays blank, never spurious
    assert row["language"] == ""
    assert row["country"] == ""
    assert row["synopsis"] == ""


def test_sfs_somerset_films_get_their_own_rows_keyed_by_theme(tmp_path):
    """BLUE VELVET screened under SFS Somerset is a different film-run from the
    same title screened under a Filmhouse season (Pink Screen), so both archive
    as distinct rows — keyed by title + year + themes."""
    path = str(tmp_path / "films.csv")
    store = HistoryStore(path)
    store.update([_filmhouse_film(title="BLUE VELVET", themes=["Pink Screen"]),
                  _sfs_film(title="BLUE VELVET", category="SFS Somerset")])

    rows = _load(path)
    assert len(rows) == 2
    assert {r["themes"] for r in rows} == {"Pink Screen", "SFS Somerset"}
    assert {r["source"] for r in rows} == {"filmhouse", "sfs"}


def test_filmhouse_format_flags_are_ored_across_runs(tmp_path):
    """A later scrape that adds a 4K / Q&A / premiere tag sets the flag once and
    for all — it never unsets a previously-seen flag."""
    path = str(tmp_path / "films.csv")
    store = HistoryStore(path)
    store.update([_filmhouse_film(tags=[])])
    store.update([_filmhouse_film(tags=["4k", "q-a"])])
    store.update([_filmhouse_film(tags=[])])

    [row] = _load(path)
    assert row["has_4k"] == "True"
    assert row["has_qa"] == "True"
    assert row["is_premiere"] == "False"


def test_screening_dates_union_and_extend_across_runs(tmp_path):
    """Re-scraping the same film-run (same title+year+themes) with additional
    screenings unions the dates and extends the range — additive, never
    overwrite, because a scrape only sees currently-listed screenings."""
    path = str(tmp_path / "films.csv")
    store = HistoryStore(path)
    store.update([_filmhouse_film(themes=["Pink Screen"],
                                  screenings=[{"start": datetime(2026, 6, 24, 19, 30)}])])
    store.update([_filmhouse_film(themes=["Pink Screen"],
                                  screenings=[{"start": datetime(2026, 6, 25, 19, 30)}])])

    [row] = _load(path)
    assert row["themes"] == "Pink Screen"
    assert row["screening_count"] == "2"
    assert row["screening_dates"] == "2026-06-24T19:30:00|2026-06-25T19:30:00"
    assert row["first_screening"] == "2026-06-24T19:30:00"
    assert row["last_screening"] == "2026-06-25T19:30:00"


def test_idempotent_rerun_adds_nothing(tmp_path):
    """Re-scraping the same set produces 0 new rows and no inflated counts."""
    path = str(tmp_path / "films.csv")
    store = HistoryStore(path)
    films = [_filmhouse_film(), _sfs_film()]
    first = store.update(films)
    second = store.update(films)

    assert first == {"total": 2, "new": 2}
    assert second == {"total": 2, "new": 0}
    rows = _load(path)
    assert len(rows) == 2
    for row in rows:
        assert row["screening_count"] == "1"


def test_multiday_all_day_sfs_festival_records_start_date(tmp_path):
    """An SFS multi-day festival row with no per-day schedule (the one case the
    advanced scraper does not expand into discrete screenings) still archives:
    recorded under its start date, not lost."""
    path = str(tmp_path / "films.csv")
    store = HistoryStore(path)
    store.update([_sfs_film(
        title="SFS Film Festival", category="SFS Film Festival",
        screenings=[{"start": datetime(2026, 8, 1, 0, 0),
                     "end": datetime(2026, 8, 4, 0, 0), "time_str": "Various"}],
    )])
    [row] = _load(path)
    assert row["screening_dates"] == "2026-08-01"
    assert row["first_screening"] == "2026-08-01"


def test_existing_csv_round_trips(tmp_path):
    """Rows written are read back unchanged on the next run (stable schema)."""
    path = str(tmp_path / "films.csv")
    HistoryStore(path).update([_filmhouse_film()])
    HistoryStore(path).update([_sfs_film()])
    rows = _load(path)
    assert len(rows) == 2
    # header matches FIELDS exactly
    assert list(rows[0].keys()) == [
        "film_id", "source", "title", "year", "director", "cast", "genre",
        "rating", "duration_mins", "language", "country", "synopsis",
        "poster_url", "themes", "has_4k", "has_qa", "is_premiere", "venues",
        "screening_count", "first_screening", "last_screening",
        "screening_dates", "first_seen", "last_seen",
    ]