"""Export scraped screenings to a flat JSON feed for the static web view.

The historic archive (``data/films.csv``) unions venues and dates across a
whole film-run, which loses the per-screening date/venue link the weekly view
needs. This module instead flattens the live scrape into one record per
screening — the ``(film, datetime, cinema, booking link)`` grain the page
renders — and writes it to ``docs/screenings.json`` for GitHub Pages to serve.
"""

import json
from datetime import datetime
from typing import Dict, List

DEFAULT_VENUE = "Filmhouse Cinemas, Singapore"


def _venue(film: Dict) -> str:
    """Best-effort venue for a film, mirroring the history archive's rule."""
    venue = (film.get("venue") or "").strip()
    if venue:
        return venue
    return DEFAULT_VENUE if film.get("source") != "sfs" else "Singapore Film Society"


def _flatten(films: List[Dict]) -> List[Dict]:
    """Turn nested film → screenings into one flat record per screening."""
    rows: List[Dict] = []
    for film in films:
        tags = set(film.get("tags") or [])
        venue = _venue(film)
        for scr in film.get("screenings") or []:
            start = scr.get("start")
            end = scr.get("end")
            rows.append(
                {
                    "title": film.get("title", ""),
                    "year": str(film.get("year") or ""),
                    "director": film.get("director", ""),
                    "genre": film.get("genre", ""),
                    "rating": film.get("rating", ""),
                    "duration_mins": film.get("duration_mins", 0),
                    "poster_url": film.get("poster_url", ""),
                    "source": film.get("source", "filmhouse"),
                    "venue": venue,
                    "has_4k": "4k" in tags,
                    "has_qa": "q-a" in tags,
                    "is_premiere": "premiere" in tags,
                    "start": start.isoformat() if isinstance(start, datetime) else "",
                    "end": end.isoformat() if isinstance(end, datetime) else "",
                    "time_str": scr.get("time_str", ""),
                    "booking_url": scr.get("booking_url", ""),
                    "film_url": film.get("url", ""),
                }
            )
    rows.sort(key=lambda r: (r["start"], r["title"]))
    return rows


def export_screenings(films: List[Dict], path: str) -> int:
    """Write the flat screening feed to ``path``. Returns the record count."""
    rows = _flatten(films)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "screenings": rows,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return len(rows)
