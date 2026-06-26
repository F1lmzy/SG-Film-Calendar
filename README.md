# SG Film Calendar

Automatically scrape film screenings from [Filmhouse.sg](https://filmhouse.sg/films/) and [Singapore Film Society](https://www.singaporefilmsociety.com/), then sync them to a shared Google Calendar.

## Features

- **Filmhouse.sg** — scrapes film title, duration, rating, genre, director, cast, and all screening times
- **Singapore Film Society** — reads the public events Google Sheet (categories, venues, promo codes, booking links)
- Creates or updates Google Calendar events for each screening
- Deduplication via deterministic event IDs
- Runs daily at 6 AM SGT via GitHub Actions

## Data Sources

| Source | URL | Method |
|--------|-----|--------|
| Filmhouse.sg | https://filmhouse.sg/films/ | HTML scrape via `scrapling` |
| Singapore Film Society | https://www.singaporefilmsociety.com/ | Public Google Sheet CSV |

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
├── main.py          # Entry point (runs all scrapers)
├── scraper.py       # Filmhouse.sg scraper
├── sfs_scraper.py   # Singapore Film Society scraper
├── calendar_sync.py # Google Calendar API client
└── validate.py      # Credential validation script
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
