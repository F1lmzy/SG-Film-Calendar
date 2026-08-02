"""Scraper for Filmhouse.sg film screenings."""

from collections import defaultdict
from datetime import date, datetime, timedelta
import re
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

from scrapling.fetchers import Fetcher

# Row classes Filmhouse uses to flag a film's screenings.
FORMAT_TAGS = {"4k", "q-a", "premiere"}

# Known languages, used to extract the spoken language(s) from synopsis prose
# like "In Chinese and French with English subtitles" without matching arbitrary
# text. Only languages listed here are recognised.
LANGUAGES = {
    # East & Southeast Asian
    "English",
    "Mandarin",
    "Cantonese",
    "Chinese",
    "Hokkien",
    "Teochew",
    "Hakka",
    "Hainanese",
    "Japanese",
    "Korean",
    "Vietnamese",
    "Thai",
    "Lao",
    "Khmer",
    "Burmese",
    "Indonesian",
    "Malay",
    "Filipino",
    "Tagalog",
    "Cebuano",
    "Javanese",
    "Sundanese",
    "Mongolian",
    "Tibetan",
    # South Asian
    "Hindi",
    "Urdu",
    "Tamil",
    "Telugu",
    "Malayalam",
    "Kannada",
    "Bengali",
    "Punjabi",
    "Marathi",
    "Gujarati",
    "Odia",
    "Assamese",
    "Nepali",
    "Sinhala",
    "Sinhalese",
    "Dari",
    "Pashto",
    "Persian",
    "Farsi",
    # West Asian & African
    "Arabic",
    "Hebrew",
    "Turkish",
    "Kurdish",
    "Armenian",
    "Georgian",
    "Azerbaijani",
    "Swahili",
    "Amharic",
    "Hausa",
    "Yoruba",
    "Igbo",
    "Zulu",
    "Xhosa",
    "Afrikaans",
    "Somali",
    "Wolof",
    # European — Romance
    "French",
    "Italian",
    "Spanish",
    "Portuguese",
    "Romanian",
    "Catalan",
    "Galician",
    # European — Germanic
    "German",
    "Dutch",
    "Flemish",
    "Swedish",
    "Danish",
    "Norwegian",
    "Icelandic",
    "Yiddish",
    # European — Slavic & Baltic
    "Russian",
    "Polish",
    "Ukrainian",
    "Czech",
    "Slovak",
    "Bulgarian",
    "Serbian",
    "Croatian",
    "Bosnian",
    "Slovenian",
    "Macedonian",
    "Belarusian",
    "Lithuanian",
    "Latvian",
    "Estonian",
    # European — other
    "Greek",
    "Hungarian",
    "Finnish",
    "Albanian",
    "Maltese",
    "Welsh",
    "Irish",
    "Basque",
    # Latin American & other
    "Quechua",
    "Guarani",
    "Nahuatl",
    "Creole",
    "Esperanto",
    "Latin",
}

# Nationality adjectives mapped to country, used to infer a film's country of
# origin from synopsis prose. Only counted when followed by a film-context noun
# (see _NATION_NOUNS), so "a French classic" → France but "French toast" → none.
COUNTRY_BY_NATIONALITY = {
    "American": "United States",
    "British": "United Kingdom",
    "Scottish": "United Kingdom",
    "Welsh": "United Kingdom",
    "Irish": "Ireland",
    "French": "France",
    "Italian": "Italy",
    "Spanish": "Spain",
    "German": "Germany",
    "Austrian": "Austria",
    "Swiss": "Switzerland",
    "Belgian": "Belgium",
    "Dutch": "Netherlands",
    "Portuguese": "Portugal",
    "Greek": "Greece",
    "Polish": "Poland",
    "Czech": "Czech Republic",
    "Hungarian": "Hungary",
    "Romanian": "Romania",
    "Russian": "Russia",
    "Ukrainian": "Ukraine",
    "Swedish": "Sweden",
    "Norwegian": "Norway",
    "Danish": "Denmark",
    "Finnish": "Finland",
    "Icelandic": "Iceland",
    "Turkish": "Türkiye",
    "Iranian": "Iran",
    "Israeli": "Israel",
    "Palestinian": "Palestine",
    "Egyptian": "Egypt",
    "Lebanese": "Lebanon",
    "Japanese": "Japan",
    "Korean": "South Korea",
    "Chinese": "China",
    "Taiwanese": "Taiwan",
    "Thai": "Thailand",
    "Vietnamese": "Vietnam",
    "Filipino": "Philippines",
    "Indonesian": "Indonesia",
    "Malaysian": "Malaysia",
    "Singaporean": "Singapore",
    "Indian": "India",
    "Australian": "Australia",
    "Canadian": "Canada",
    "Mexican": "Mexico",
    "Brazilian": "Brazil",
    "Argentine": "Argentina",
    "Argentinian": "Argentina",
}

# Multi-word nationalities handled separately (regex can't word-split these).
_MULTIWORD_NATIONALITY = {
    "South Korean": "South Korea",
    "Hong Kong": "Hong Kong",
}

# Nouns that, following a nationality, signal it describes the film's origin.
_NATION_NOUNS = (
    r"film|movie|drama|comedy|documentary|production|director|filmmaker|"
    r"animation|anime|feature|masterpiece|classic|thriller|romance|epic|"
    r"horror|western|musical|adaptation"
)


class FilmhouseScraper:
    """Scrape film screening data from Filmhouse.sg."""

    BASE_URL = "https://filmhouse.sg/"
    URL = "https://filmhouse.sg/films/"

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now()

    def scrape(self) -> List[Dict]:
        """Fetch and parse all film screenings, tagged with their seasons."""
        page = Fetcher.get(self.URL)
        season_map = self._build_season_membership(page)

        films: List[Dict] = []
        for film_el in page.css(".jacro-event.movie-tabs"):
            film = self._parse_film(film_el)
            if film and film["screenings"]:
                path = self._film_path(film["url"])
                film["themes"] = sorted(season_map.get(path, set()))
                films.append(film)

        return films

    def _build_season_membership(self, page) -> Dict[str, Set[str]]:
        """Map each film's URL path to the set of season names it appears in.

        Filmhouse lists curated seasons (e.g. "Pink Screen", "Music in Film")
        as nav links to /seasons-events/<slug>/ pages. Each season page reuses
        the same film-listing markup, so membership is derived by matching film
        URLs across those pages.
        """
        season_links: Dict[str, str] = {}
        for anchor in page.css("a.elementor-sub-item"):
            href = anchor.css("::attr(href)").get() or ""
            name = (anchor.css("::text").get() or "").strip()
            if "/seasons-events/" in href and name:
                season_links[name] = urljoin(self.BASE_URL, href)

        membership: Dict[str, Set[str]] = defaultdict(set)
        for name, url in season_links.items():
            try:
                season_page = Fetcher.get(url)
            except Exception as exc:  # noqa: BLE001 - one bad season shouldn't abort
                print(f"  ! failed to fetch season '{name}': {exc}")
                continue
            for film_el in season_page.css(".jacro-event.movie-tabs"):
                href = film_el.css(".liveeventtitle::attr(href)").get() or ""
                path = self._film_path(href)
                if path:
                    membership[path].add(name)

        return membership

    @staticmethod
    def _film_path(url: str) -> str:
        """Normalise a film URL to its stable /film/<id>/<slug> path."""
        match = re.search(r"/film/\d+/[^/?#]+", url)
        return match.group(0) if match else url

    def _parse_film(self, film_el) -> Optional[Dict]:
        """Parse a single film element."""
        title = film_el.css(".liveeventtitle::text").get()
        if not title:
            return None

        film_url = film_el.css(".liveeventtitle::attr(href)").get() or ""
        duration_mins = self._extract_duration(film_el)
        year, rating, genre = self._extract_metadata(film_el)
        director, cast = self._extract_credits(film_el)
        synopsis = self._extract_synopsis(film_el)
        screenings = self._parse_screenings(film_el, duration_mins)

        return {
            "title": title.strip(),
            "url": film_url,
            "year": year,
            "duration_mins": duration_mins,
            "rating": rating,
            "genre": genre,
            "director": director,
            "cast": cast,
            "language": self._extract_languages(synopsis),
            "country": self._extract_country(synopsis),
            "synopsis": synopsis,
            "poster_url": self._extract_poster(film_el),
            "tags": self._extract_tags(film_el),
            "source": "filmhouse",
            "screenings": screenings,
        }

    @staticmethod
    def _extract_poster(film_el) -> str:
        """Extract the poster image URL, ignoring the default placeholder."""
        src = film_el.css(".film_img img::attr(src)").get() or ""
        return "" if "default.png" in src else src.strip()

    @staticmethod
    def _extract_synopsis(film_el) -> str:
        """Extract synopsis text from the formatted description block."""
        parts = film_el.css(".jacro-formatted-text ::text").getall()
        text = " ".join(p.strip() for p in parts if p.strip())
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_languages(synopsis: str) -> str:
        """Best-effort spoken language(s) from synopsis prose.

        Filmhouse synopses carry a spec like "In Chinese and French with English
        subtitles" or "In Korean with English subtitles. Rated M18". The spoken
        languages are the list right after "In", before any "with ... subtitles"
        or rating. Returns them pipe-joined, ignoring subtitle languages.
        """
        for match in re.finditer(
            r"\bIn\s+([A-Za-z][A-Za-z ,&]*?)"
            r"(?=\s+with\b|\s+Rated\b|\s+Rating\b|[.;,]|\s*$)",
            synopsis,
        ):
            tokens = re.split(r"[\s&]+|\band\b", match.group(1))
            langs = [t for t in tokens if t in LANGUAGES]
            if langs:
                return "|".join(dict.fromkeys(langs))
        return ""

    @staticmethod
    def _extract_country(synopsis: str) -> str:
        """Best-effort country of origin from synopsis prose.

        Conservative: a nationality only counts when immediately followed by a
        film-context noun (e.g. "a French classic", "South Korean director"), so
        languages-as-adjectives and incidental mentions are not misread. Returns
        countries pipe-joined; usually empty, since the source rarely states it.
        """
        found: List[str] = []
        for adj, country in _MULTIWORD_NATIONALITY.items():
            if re.search(rf"\b{adj}\s+(?:{_NATION_NOUNS})\b", synopsis):
                found.append(country)

        for match in re.finditer(rf"\b([A-Z][a-z]+)\s+(?:{_NATION_NOUNS})\b", synopsis):
            country = COUNTRY_BY_NATIONALITY.get(match.group(1))
            if country:
                found.append(country)

        return "|".join(dict.fromkeys(found))

    def _extract_tags(self, film_el) -> List[str]:
        """Extract format/event flags (4k, q-a, premiere) from the row class."""
        classes = (film_el.attrib.get("class") or "").split()
        return sorted(set(classes) & FORMAT_TAGS)

    def _extract_duration(self, film_el) -> int:
        """Extract film duration in minutes."""
        for span in film_el.css(".running-time span::text").getall():
            match = re.search(r"(\d+)\s*mins", span, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return 120

    def _extract_metadata(self, film_el) -> tuple:
        """Extract year, rating, and genre."""
        year = rating = genre = ""
        for text in film_el.css(".running-time span::text").getall():
            text = text.strip()
            if text.isdigit() and len(text) == 4:
                year = text
            elif text.startswith("(") and text.endswith(")"):
                rating = text
            elif "mins" not in text.lower() and text:
                genre = text
        return year, rating, genre

    def _extract_credits(self, film_el) -> tuple:
        """Extract director and cast."""
        director = cast = ""
        for text in film_el.css(".film-info span::text").getall():
            text = text.strip()
            if text.startswith("Directed by"):
                director = text.replace("Directed by", "").strip()
            elif text.startswith("Starring"):
                cast = text.replace("Starring", "").strip()
        return director, cast

    def _parse_screenings(self, film_el, duration_mins: int) -> List[Dict]:
        """Parse all screenings for a film."""
        screenings: List[Dict] = []
        perf_lists = film_el.css(".performance-list-items")

        if not perf_lists:
            return screenings

        perf_list = perf_lists[0]
        current_date: Optional[date] = None

        # Use XPath for direct children (cssselect doesn't support '> selector')
        children = perf_list.xpath('./div[contains(@class, "heading")] | ./li')

        for child in children:
            classes = child.attrib.get("class", "").split()

            if "heading" in classes:
                heading_text = child.css("::text").get() or ""
                current_date = self._parse_date_heading(heading_text)
                continue

            if current_date is None:
                continue

            time_text = child.css(".film_book_button .time::text").get()
            if not time_text:
                continue

            book_url = child.css(".film_book_button::attr(href)").get() or ""
            # Format flags (4k/q-a/premiere) live on the individual screening
            # <li>, not just the aggregated film row, so a film can have a single
            # 4K or Q&A screening among otherwise plain ones.
            tags = sorted(set(classes) & FORMAT_TAGS)

            try:
                time_obj = datetime.strptime(time_text.strip(), "%I:%M %p").time()
                start_dt = datetime.combine(current_date, time_obj)
                end_dt = start_dt + timedelta(minutes=duration_mins)

                screenings.append(
                    {
                        "start": start_dt,
                        "end": end_dt,
                        "booking_url": book_url,
                        "time_str": time_text.strip(),
                        "tags": tags,
                    }
                )
            except ValueError:
                continue

        return screenings

    def _parse_date_heading(self, heading_text: str) -> Optional[date]:
        """Parse date heading like 'Thursday 14th May' into a date."""
        cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", heading_text)

        for year_offset in [0, 1, -1]:
            year = self.reference_date.year + year_offset
            try:
                parsed = datetime.strptime(f"{cleaned} {year}", "%A %d %B %Y")
                result_date = parsed.date()
                days_diff = (result_date - self.reference_date.date()).days
                if -30 <= days_diff <= 365:
                    return result_date
            except ValueError:
                continue

        return None
