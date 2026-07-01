# 1stTix Checker — San Diego - Project Context

## Overview
Automated checker for **1sttix.org** that:
1. Logs into the 1stTix member portal (reusing cached session cookies when valid)
2. Fetches available California FCFS (first come first served) shows
3. **Filters to San Diego area only** — cities within ~45 min of Talmadge
4. Filters out shows on a denylist (contains-based matching, case-insensitive)
5. Sends email notifications for NEW shows only (tracks show+date combinations)
6. **Detects RARE shows** — flags shows that don't appear frequently 🔥
7. **Adds AI descriptions** — a one-line GPT summary + star rating per show (cached)
8. Assigns a **popularity label** (New! / Rare find / Occasional / Regular / Always available)
9. Includes ChatGPT links to ask "Should I go to this show?"
10. **Runs every 30 minutes via GitHub Actions on a self-hosted runner**
11. Uses random delays / random-skip / backoff between requests to avoid bot detection
12. Auto-commits available shows and publishes to GitHub Pages
13. **All timestamps in Pacific Time (PT)**
14. **Groups shows by name** — both website and emails group multiple time slots under each show
15. **Graceful failure handling** — login failures skip writing, preserving previous data
16. **`last_successful_run` timestamp** — confirms scrapes are actually succeeding (gated on ≥1 show)

## Run mechanism — GitHub Actions (self-hosted runner)
The live scheduler is **`.github/workflows/check-shows.yml`**: cron `*/30 * * * *` + manual `workflow_dispatch`,
`runs-on: self-hosted` with `contents: write`. It checks out, installs `requirements.txt`, configures git as
`github-actions[bot]`, and runs `python firsttix_checker.py --fast`. The script itself does the git commit &
push (the recurring "Update 1stTix shows - <ts>" commits are these runs).

The runner is **self-hosted** (not `ubuntu-latest`) because cloud IPs are blocked/challenged by 1sttix.org —
`.github/workflows/test-access.yml` (manual only) exists to probe login-page reachability + response headers
from a given runner. Keep the self-hosted runner online for the checker to run.

> **Legacy:** this project used to run via **macOS launchd** every 30 min (`com.rsua.firsttix-checker.plist`,
> `setup.sh`, `run.sh`). Those files still exist but the plist/launchd path is no longer the live scheduler.
> ⚠️ **Do not commit real credentials in `com.rsua.firsttix-checker.plist`** — it is tracked in this public repo.
> Secrets belong only in GitHub Actions repo secrets (see Configuration).

## Live Pages

| Link | Purpose |
|------|---------|
| **[View Available Shows](https://suacide24.github.io/firsttix-checker/)** | Mobile-friendly page with San Diego 1stTix shows |
| **[GitHub Repo](https://github.com/suacide24/firsttix-checker)** | Source code |
| **[Edit Denylist](https://gist.github.com/suacide24/f1bf569e229cf1319137a4230d7db1b6/edit)** | Add shows to filter out |

## Key Files

| File | Purpose |
|------|---------|
| `firsttix_checker.py` | Main script (~1500 lines) |
| `index.html` | GitHub Pages frontend (fetches `firsttix_shows.json`) |
| `firsttix_shows.json` | 1stTix shows data (written each run; committed) |
| `notified_shows.json` | Tracks which show+date combos have been notified |
| `show_history.json` | Tracks show appearances over time for RARE / popularity |
| `ai_descriptions.json` | Cache of GPT one-line descriptions, keyed by lowercased show name |
| `denylist.txt` | Local fallback denylist (primary is a GitHub Gist) |
| `.github/workflows/check-shows.yml` | Scheduled runner (every 30 min) |
| `.github/workflows/test-access.yml` | Manual site-reachability probe |
| `com.rsua.firsttix-checker.plist` | **Legacy** macOS launchd config (no longer the live scheduler) |
| `setup.sh` | **Legacy** launchd installer |
| `run.sh` | **Legacy** local wrapper with credentials (gitignored) |
| `requirements.txt` | Python deps (`requests`, `beautifulsoup4`) |

Gitignored state/secret files: `run.sh`, `session_cookies.pkl`, `backoff_state.json`, `*.log`.

## Pipeline (main flow in `firsttix_checker.py`)
1. Backoff check + 15% random-skip (`should_skip_due_to_backoff`, `should_random_skip`)
2. Load denylist + previously-notified set; create session with random User-Agent
3. Reuse `session_cookies.pkl` if `verify_session` passes; otherwise `login_firsttix` and re-cache cookies
4. `fetch_firsttix_shows` — paginated `?status=fcfs&state=ca`
5. `filter_by_location` (San Diego area) → `filter_shows` (denylist)
6. `update_show_history` → `cleanup_old_history` (90d) → `mark_rare_shows` → `get_popularity_label`
7. `enrich_shows_with_ai` (OpenAI, capped at 5 new calls/run, rest served from cache)
8. `save_shows` — strips internal `location`/`venue` fields; sets `last_successful_run` only if ≥1 raw show
9. `push_to_github` — commits the four data JSONs, rebases `-X theirs`, pushes
10. `find_new_shows` → email (`send_email_notification`) + macOS `notify_user` for genuinely new show+date combos

## 📍 San Diego Area Filter
The 1stTix API is queried with `state=ca`. A second local filter (`filter_by_location`) keeps only shows whose
venue/location text matches a city within ~45 minutes of **Talmadge, San Diego** (`ALLOWED_CITIES`). Events with
no recognizable city are **excluded**.

| Area | Cities |
|------|--------|
| **San Diego proper** | All neighborhoods (Talmadge, La Jolla, Pacific Beach, Gaslamp, Downtown, Mission Valley, etc.) |
| **South county** | Chula Vista, National City, Coronado, Imperial Beach, Bonita, Lemon Grove, Spring Valley |
| **East county** | La Mesa, El Cajon, Santee, Lakeside, Alpine, Ramona |
| **North county coastal** | Del Mar, Solana Beach, Encinitas, Carlsbad, Oceanside |
| **North county inland** | Escondido, Poway, Rancho Santa Fe, Vista, San Marcos, Fallbrook |

## 🔥 RARE Show Detection & Popularity
Backed by `show_history.json` (appearance dates per show name).

| Setting | Value |
|---------|-------|
| Lookback period | 30 days (`RARE_THRESHOLD_DAYS`) |
| Rare threshold | < 3 appearances (`RARE_THRESHOLD_COUNT`) |
| History cleanup | 90 days (old entries auto-removed) |

Popularity label (recent-30d appearance count): 0 → **New! ✨**, 1–2 → **Rare find 🔥**,
3–7 → **Occasional 🎯**, 8–15 → **Regular 📅**, 16+ → **Always available ♻️**.

## 🤖 AI Descriptions
`enrich_shows_with_ai` calls **OpenAI `gpt-4o-mini`** for a ≤15-word description + `⭐ X/5` rating per show.
Results are cached in `ai_descriptions.json` (key = lowercased show name); **max 5 new API calls per run** to cap
cost. Requires `OPENAI_API_KEY`; if unset, this step is skipped and everything else still works.

## Anti-bot behavior
- Random User-Agent per session; random delays between requests/pages (skipped under `--fast`)
- 15% random per-run skip (`RANDOM_SKIP_CHANCE`)
- Exponential login-failure backoff: base 30 min → max 8h (`backoff_state.json`, gitignored)
- Session-cookie reuse to minimize logins

## Configuration
Secrets are provided as **GitHub Actions repo secrets** (consumed via `env:` in `check-shows.yml`):

| Variable | Purpose |
|----------|---------|
| `FIRSTTIX_EMAIL` | 1stTix login email (`ryan.sua.rn@gmail.com`) |
| `FIRSTTIX_PASSWORD` | 1stTix password |
| `SMTP_EMAIL` | Gmail sender address |
| `SMTP_PASSWORD` | Gmail App Password (16-char) |
| `NOTIFICATION_EMAIL` | Email to receive notifications (`rsua95@gmail.com`) |
| `OPENAI_API_KEY` | OpenAI key for AI descriptions (optional) |

For legacy local runs the same values came from `run.sh` / the launchd plist's `EnvironmentVariables`.
**Never commit real secret values** — the tracked plist is public.

## Denylist Behavior
- **Primary:** GitHub Gist at https://gist.github.com/suacide24/f1bf569e229cf1319137a4230d7db1b6
- **Fallback:** Local `denylist.txt` file
- Lines starting with `#` are ignored (comments)
- **Contains-based matching** — if "comedy" is in denylist, it filters "L.A. Comedy Club"
- Case-insensitive

## Manual Operations
```bash
# Run manually (Actions: use the "Check 1stTix Shows" workflow → Run workflow)
python3 firsttix_checker.py --fast     # needs env vars set (FIRSTTIX_*, SMTP_*, etc.)

# Probe whether a runner can reach 1sttix.org (Actions: "Test Site Access" → Run workflow)

# Reset notifications (will re-notify for all shows)
echo '{"notified": []}' > notified_shows.json

# Reset RARE / popularity history
echo '{"shows": {}}' > show_history.json

# Clear AI description cache
echo '{}' > ai_descriptions.json

# --- Legacy launchd (only if running locally instead of Actions) ---
./setup.sh                                                     # install job
launchctl unload ~/Library/LaunchAgents/com.rsua.firsttix-checker.plist   # uninstall
```

## 1stTix Site Structure
- **Login URL:** `https://www.1sttix.org/login`
- **Login form fields:** `email`, `password`
- **Events URL:** `https://www.1sttix.org/tixer/get-tickets/events/{page}?status=fcfs&state=ca`
- **Pagination:** Page number is in the URL path (`/events/1`, `/events/2`, etc.)
- **Query params:** `status=fcfs` (first come first served), `state=ca` (California only)
- **Event data:** Returns HTML with `div.event` containers
  - Name: `img[alt]` or `.entry-title`
  - Date: `.entry-meta` (parsed with regex)
  - Link: `a[href*="get-tickets/event"]`
  - Location: extracted from full event text for San Diego area filtering
- **Sponsor filtering:** Events matching sponsor keywords (tactical, coursera, etc.) are skipped
- **Non-event filtering:** Items without a date or event link are skipped

## Related Project
HouseSeats (Las Vegas) checker lives in a separate repo (GitHub Pages:
https://suacide24.github.io/houseseats-checker/). Also distinct from the CBVA beach-volleyball
monitor (`suacide24/cbva-monitor`).

---
*Last updated: 2026-06-30*
