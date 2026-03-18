# 1stTix Checker — San Diego - Project Context

## Overview
Automated checker for **1sttix.org** that:
1. Logs into the 1stTix member portal
2. Fetches available shows
3. **Filters to San Diego area only** — cities within ~45 min of Talmadge
4. Filters out shows on a denylist (contains-based matching, case-insensitive)
5. Sends email notifications for NEW shows only (tracks show+date combinations)
6. **Detects RARE shows** — flags shows that don't appear frequently 🔥
7. Includes ChatGPT links to ask "Should I go to this show?"
8. Runs locally via macOS launchd every 30 minutes
9. Uses random delays between requests to avoid bot detection
10. Auto-publishes available shows to GitHub Pages
11. **All timestamps in Pacific Time (PT)**
12. **Groups shows by name** — both website and emails group multiple time slots under each show
13. **Graceful failure handling** — login failures skip writing, preserving previous data
14. **`last_successful_run` timestamp** — confirms scripts are actively running (gated on ≥1 show)

## Live Pages

| Link | Purpose |
|------|---------|
| **[View Available Shows](https://suacide24.github.io/firsttix-checker/)** | Mobile-friendly page with San Diego 1stTix shows |
| **[Edit Denylist](https://gist.github.com/suacide24/f1bf569e229cf1319137a4230d7db1b6/edit)** | Add shows to filter out |

## Key Files

| File | Purpose |
|------|---------|
| `firsttix_checker.py` | Main script |
| `index.html` | GitHub Pages frontend (fetches `firsttix_shows.json`) |
| `firsttix_shows.json` | 1stTix shows data (written by local launchd) |
| `notified_shows.json` | Tracks which show+date combos have been notified |
| `show_history.json` | Tracks show appearances over time for RARE detection |
| `requirements.txt` | Python dependencies |
| `denylist.txt` | Local fallback denylist (primary is on GitHub Gist) |
| `run.sh` | Local wrapper script with credentials (in .gitignore) |
| `com.rsua.firsttix-checker.plist` | macOS launchd config for local scheduled runs |
| `setup.sh` | Installs the launchd job |

## Architecture

```
┌──────────────────────────────┐
│   Local macOS launchd         │
│   (runs every 30 mins)        │
│   --fast                      │
├──────────────────────────────┤
│ 1. Fetch events from 1stTix   │
│ 2. Filter to San Diego area   │
│ 3. Filter by denylist          │
│ 4. Detect RARE shows           │
│ 5. Send email notifications    │
│ 6. Write firsttix_shows.json  │
│ 7. git commit & push           │
└──────────────┬───────────────┘
               ▼
     GitHub Pages serves
     index.html which fetches
     firsttix_shows.json
```

## 📍 San Diego Area Filter

Shows are only included if their venue/location text matches a city within ~45 minutes of **Talmadge, San Diego**. The `ALLOWED_CITIES` set includes:

| Area | Cities |
|------|--------|
| **San Diego proper** | All neighborhoods (Talmadge, La Jolla, Pacific Beach, Gaslamp, etc.) |
| **South county** | Chula Vista, National City, Coronado, Imperial Beach, Bonita, Lemon Grove, Spring Valley |
| **East county** | La Mesa, El Cajon, Santee, Lakeside, Alpine, Ramona |
| **North county coastal** | Del Mar, Solana Beach, Encinitas, Carlsbad, Oceanside |
| **North county inland** | Escondido, Poway, Rancho Santa Fe, Vista, San Marcos, Fallbrook |

Events with no recognizable city in their text are **excluded**.

## 🔥 RARE Show Detection

| Setting | Value |
|---------|-------|
| Lookback period | 30 days |
| Rare threshold | < 3 appearances |
| History cleanup | 90 days (old entries auto-removed) |

## Configuration

Credentials stored in `run.sh` (gitignored) and launchd plist environment variables:

| Variable | Purpose |
|----------|---------|
| `FIRSTTIX_EMAIL` | 1stTix login email |
| `FIRSTTIX_PASSWORD` | 1stTix password |
| `SMTP_EMAIL` | Gmail sender address |
| `SMTP_PASSWORD` | Gmail App Password (16-char) |
| `NOTIFICATION_EMAIL` | Email to receive notifications |

## Denylist Behavior

- **Primary:** GitHub Gist at https://gist.github.com/suacide24/f1bf569e229cf1319137a4230d7db1b6
- **Fallback:** Local `denylist.txt` file
- Lines starting with `#` are ignored (comments)
- **Contains-based matching** — if "comedy" is in denylist, it filters "L.A. Comedy Club"
- Case-insensitive

## Manual Operations

```bash
# Run manually
./run.sh --fast

# Or with environment variables set:
python3 firsttix_checker.py --fast

# Install/reinstall the launchd job
./setup.sh

# Uninstall
launchctl unload ~/Library/LaunchAgents/com.rsua.firsttix-checker.plist
rm ~/Library/LaunchAgents/com.rsua.firsttix-checker.plist

# Reset notifications (will re-notify for all shows)
echo '{"notified": []}' > notified_shows.json

# Reset RARE detection
echo '{"shows": {}}' > show_history.json
```

## 1stTix Site Structure

- **Login URL:** `https://www.1sttix.org/login`
- **Login form fields:** `email`, `password`
- **Events URL:** `https://www.1sttix.org/tixer/get-tickets/events`
- **Event data:** Returns HTML with `div.event` containers
  - Name: `img[alt]` or `.entry-title`
  - Date: `.entry-meta` (parsed with regex)
  - Link: `a[href*="get-tickets/event"]`
  - Location: extracted from event text for San Diego filtering

## Related Project

HouseSeats (Las Vegas) checker lives in a separate repo: `/Users/rsua/houseseats-checker/`

---
*Last updated: 2026-03-18*
