# SG Film Calendar

Automatically scrape film screenings from [Filmhouse.sg](https://filmhouse.sg/films/) and [Singapore Film Society](https://www.singaporefilmsociety.com/), then sync them to a shared Google Calendar **and** accumulate a historic archive for later analysis.

## Features

- **Filmhouse.sg** — scrapes film title, duration, rating, genre, director, cast, curated season/theme, format flags (4K, Q&A, premiere), language, country, synopsis, poster, and all screening times
- **Singapore Film Society** — reads two live sources:
  - the public events Google Sheet + Peatix pages (SFS Somerset bundles expanded into individual films with discrete screenings)
  - the newer **Eventive** schedule at <https://singaporefilmsociety.eventive.org/schedule>, where SFS now publishes new screenings (reads Eventive's JSON API via `scrapling`, discovering the bucket/api-key from the schedule page's tenant bundle)
- Creates or updates Google Calendar events for each screening
- Deduplication via deterministic event IDs
- **Historic archive** — accumulates every screening from both sources into `data/films.csv` over time (see below)
- Runs daily at 6 AM SGT via GitHub Actions

## Historic Archive

Each run merges the day's scrape from **both** Filmhouse and SFS into `data/films.csv`, building a permanent record for analysis. The grain is one row per **film-run** — a film under a given set of themes — keyed on `sha256(title + year + sorted(themes))`. A film re-screened later under a different programme gets its own row.

SFS feeds the archive at the same grain as Filmhouse: SFS Somerset bundles are expanded into their component films before archiving, so e.g. *BLUE VELVET* screened under the "SFS Somerset" programme becomes its own row keyed by title + year + `[SFS Somerset]`, exactly like a Filmhouse film screened under a season.

Merges are additive: `source`, `themes`, `venues`, and `screening_dates` are unioned; the `has_4k` / `has_qa` / `is_premiere` flags are OR'd (true if *any* screening ever had it); and the date range is extended. Existing rows are never overwritten, since a scrape only ever sees the screenings currently listed.

Notes / limitations:

- The archive is **forward-only** — it accumulates from the day the feature shipped; the past is not backfilled.
- Two un-themed runs of the same film collapse into one row (no theme to distinguish them).
- `language` and `country` are best-effort, parsed from Filmhouse synopsis prose (the "In … with … subtitles" spec and nationality + film-context phrases). Neither SFS nor Filmhouse states them as structured fields, so `country` in particular is often blank; SFS has no synopsis at all, so its `language` / `country` / `synopsis` are empty.
- SFS `poster_url` is the programme/Peatix cover from the sheet (`Image` column); for expanded SFS Somerset films it is the bundle's poster, not each film's own.
- GitHub Actions commits the updated CSV back to the repo, so its git history doubles as a change log.

### Themes

Every scraper tags each film with a `themes` list — the curatorial programme or
season a screening belongs to (a Filmhouse season, an SFS showcase, an NLB
"Big Picture" month, an AFA festival like Singapore Shorts). Themes feed the
archive's film-run grain and are surfaced on each Google Calendar event
(`Theme: ...`). Surfacing them on the static weekly view is a follow-up that
lands with the web-view work.

## Data Sources

| Source | URL | Method |
|--------|-----|--------|
| Filmhouse.sg | https://filmhouse.sg/films/ | HTML scrape via `scrapling` |
| Singapore Film Society (Peatix) | https://www.singaporefilmsociety.com/ | Public Google Sheet CSV + Peatix pages via `scrapling` |
| Singapore Film Society (Eventive) | https://singaporefilmsociety.eventive.org/schedule | Eventive JSON API via `scrapling` (new screenings, after the Peatix migration) |
| NLB (LibCal) | https://nlb.libcal.com | Public LibCal list JSON, filtered to film/movie screenings |
| Asian Film Archive | https://asianfilmarchive.org/whatson/ | HTML scrape via `scrapling` (`mep_events` listings) |
| Objectifs | https://www.objectifs.com.sg/objectifs-cinema-now-showing/ | No dated schedule yet (returns no screenings) |

## Setup

### 1. Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable the **Google Calendar API**
4. Create a **Service Account** (IAM & Admin > Service Accounts)
5. Generate a JSON key for the service account
6. Note the service account email (e.g., `service-account@project.iam.gserviceaccount.com`)

### 2. Google Calendar

1. Create a new calendar (or use existing)
2. Go to **Settings and sharing**
3. Under **Share with specific people**, add the service account email with **Make changes to events** permission
4. Copy the **Calendar ID** (found in Settings under "Integrate calendar")

### 3. GitHub Secrets

In your GitHub repository, go to **Settings > Secrets and variables > Actions** and add:

- `GOOGLE_CALENDAR_ID`: Your Google Calendar ID
- `GOOGLE_CALENDAR_CREDENTIALS`: The entire contents of the service account JSON key file

### 4. Local Development

```bash
# Install dependencies
uv sync

# Run scraper
GOOGLE_CALENDAR_ID="your-calendar-id" \
GOOGLE_CALENDAR_CREDENTIALS='{...json...}' \
PYTHONPATH=src uv run python src/main.py

# Run scraper and remove stale SFS entries created by older scraper versions
GOOGLE_CALENDAR_ID="your-calendar-id" \
GOOGLE_CALENDAR_CREDENTIALS='{...json...}' \
CLEANUP_STALE_SFS=true \
PYTHONPATH=src uv run python src/main.py
```

## Project Structure

```
src/
├── main.py            # Entry point (runs all scrapers)
├── scraper.py         # Filmhouse.sg scraper
├── sfs_scraper.py     # Singapore Film Society — Peatix / Google Sheet scraper
├── eventive_scraper.py # Singapore Film Society — Eventive schedule scraper
├── calendar_sync.py   # Google Calendar API client
├── history.py         # Historic archive (merge-upsert to data/films.csv)
└── validate.py        # Credential validation script
data/
└── films.csv        # Accumulated historic record of film-runs
.github/
└── workflows/
    └── daily-scrape.yml  # GitHub Actions workflow
```

## How It Works

1. **Scrape Filmhouse.sg**: Uses `scrapling`'s `Fetcher` to retrieve and parse the film listings page
2. **Scrape SFS**: Downloads the public Google Sheet CSV that powers the SFS event widget
3. **Parse**: Extracts metadata, dates, times, venues, and booking links
4. **Sync**: Creates or updates Google Calendar events using a Service Account

Each screening becomes a separate calendar event with:
- Start and end times
- Source-specific metadata in the description (e.g., Filmhouse: rating, director, cast; SFS: category, event type, promo code)
- Booking / more-info link
- Location based on the venue from each source

When `CLEANUP_STALE_SFS=true`, the sync also removes old aggregate SFS Somerset entries like `24 Jun – 28 Jun Films | SFS Somerset` and any future stale SFS events that were previously tagged by this scraper.

## Manual Trigger

You can manually run the workflow from the GitHub Actions tab by selecting the **Daily SG Film Calendar Scrape** workflow and clicking **Run workflow**.
