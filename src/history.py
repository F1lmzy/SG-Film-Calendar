"""Historic archive of Singapore film screenings.

Accumulates a single denormalised CSV at film-run grain. A "run" is one film
under one set of curatorial themes, so a film re-screened under a different
programme later gets its own row. Each daily scrape merges into existing rows
(union themes/venues/screening dates, OR the format flags, extend the date
range) rather than overwriting, because a scrape only ever sees the screenings
currently listed.
"""

import csv
import hashlib
import os
from datetime import date
from typing import Dict, List

FIELDS = [
    "film_id",
    "source",
    "title",
    "year",
    "director",
    "cast",
    "genre",
    "rating",
    "duration_mins",
    "language",
    "country",
    "synopsis",
    "poster_url",
    "themes",
    "has_4k",
    "has_qa",
    "is_premiere",
    "venues",
    "screening_count",
    "first_screening",
    "last_screening",
    "screening_dates",
    "first_seen",
    "last_seen",
]

# Columns filled from the film once, and back-filled later only if still blank.
_METADATA_FIELDS = (
    "title",
    "year",
    "director",
    "cast",
    "genre",
    "rating",
    "duration_mins",
    "language",
    "country",
    "synopsis",
    "poster_url",
)

DEFAULT_VENUE = "Filmhouse Cinemas, Singapore"


class HistoryStore:
    """Read, merge, and write the film-run history CSV."""

    def __init__(self, path: str) -> None:
        self.path = path

    def update(self, films: List[Dict]) -> Dict[str, int]:
        """Merge scraped films into the archive and persist it."""
        records = self._load()
        today = date.today().isoformat()
        new = 0

        for film in films:
            key = self._run_key(film)
            if key not in records:
                new += 1
            self._merge_film(records, key, film, today)

        self._save(records)
        return {"total": len(records), "new": new}

    def _run_key(self, film: Dict) -> str:
        """Stable id for a film-run: title + production year + theme set."""
        title = (film.get("title") or "").strip().lower()
        year = str(film.get("year") or "").strip()
        themes = "|".join(sorted(self._clean(film.get("themes"))))
        raw = f"{title}|{year}|{themes}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _merge_film(
        self, records: Dict[str, Dict], key: str, film: Dict, today: str
    ) -> None:
        """Merge a single scraped film into the record for its run."""
        rec = records.get(key)
        if rec is None:
            rec = {f: "" for f in FIELDS}
            rec["film_id"] = key
            rec["first_seen"] = today
            records[key] = rec

        # Merge set-valued columns.
        rec["source"] = self._merge_set(
            rec["source"], [film.get("source", "filmhouse")]
        )
        rec["themes"] = self._merge_set(rec["themes"], self._clean(film.get("themes")))
        rec["venues"] = self._merge_set(rec["venues"], [self._venue(film)])

        dates = self._to_set(rec["screening_dates"])
        dates |= {s["start"].isoformat() for s in film.get("screenings") or []}
        sorted_dates = sorted(dates)
        rec["screening_dates"] = "|".join(sorted_dates)
        rec["screening_count"] = str(len(sorted_dates))
        rec["first_screening"] = sorted_dates[0] if sorted_dates else ""
        rec["last_screening"] = sorted_dates[-1] if sorted_dates else ""

        # OR the format flags.
        tags = set(film.get("tags") or [])
        rec["has_4k"] = self._or_flag(rec["has_4k"], "4k" in tags)
        rec["has_qa"] = self._or_flag(rec["has_qa"], "q-a" in tags)
        rec["is_premiere"] = self._or_flag(rec["is_premiere"], "premiere" in tags)

        # Fill metadata if not already populated.
        for col in _METADATA_FIELDS:
            value = film.get(col)
            if value and not rec[col]:
                rec[col] = str(value)

        rec["last_seen"] = today

    def _venue(self, film: Dict) -> str:
        venue = (film.get("venue") or "").strip()
        if venue:
            return venue
        return (
            DEFAULT_VENUE if film.get("source") != "sfs" else "Singapore Film Society"
        )

    @staticmethod
    def _clean(values) -> List[str]:
        return [v.strip() for v in (values or []) if v and v.strip()]

    @staticmethod
    def _to_set(joined: str) -> set:
        return {v for v in (joined or "").split("|") if v}

    def _merge_set(self, existing: str, additions: List[str]) -> str:
        merged = self._to_set(existing) | {
            a.strip() for a in additions if a and a.strip()
        }
        return "|".join(sorted(merged))

    @staticmethod
    def _or_flag(existing: str, new: bool) -> str:
        return "True" if existing == "True" or new else "False"

    def _load(self) -> Dict[str, Dict]:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, newline="", encoding="utf-8") as fh:
            return {row["film_id"]: row for row in csv.DictReader(fh)}

    def _save(self, records: Dict[str, Dict]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        rows = sorted(
            records.values(),
            key=lambda r: (r.get("title", "").lower(), r.get("first_screening", "")),
        )
        with open(self.path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({f: row.get(f, "") for f in FIELDS})
