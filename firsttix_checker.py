#!/usr/bin/python3
"""
1stTix Show Checker — San Diego
Logs into 1sttix.org and fetches available shows,
filtering to San Diego area (within ~45 min of Talmadge)
and filtering out any shows on the denylist.
Sends email notifications for new shows (only once per show+date).
"""

import argparse
import json
import os
import random
import re
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Pacific Time helper
# ---------------------------------------------------------------------------
def get_pacific_time():
    """Get current time in Pacific Time."""
    utc_now = datetime.now(timezone.utc)
    year = utc_now.year
    march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
    dst_start = march_first + timedelta(days=(6 - march_first.weekday() + 7) % 7 + 7)
    nov_first = datetime(year, 11, 1, tzinfo=timezone.utc)
    dst_end = nov_first + timedelta(days=(6 - nov_first.weekday()) % 7)

    if dst_start <= utc_now < dst_end:
        offset = timedelta(hours=-7)  # PDT
    else:
        offset = timedelta(hours=-8)  # PST

    return utc_now + offset


# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Check 1stTix for available shows in San Diego")
parser.add_argument(
    "--fast", "--no-delay", action="store_true", help="Skip random delays (for testing)"
)
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Configuration — 1stTix
# ---------------------------------------------------------------------------
FIRSTTIX_BASE_URL = "https://www.1sttix.org"
FIRSTTIX_LOGIN_URL = f"{FIRSTTIX_BASE_URL}/login"
FIRSTTIX_EVENTS_URL = f"{FIRSTTIX_BASE_URL}/tixer/get-tickets/events"
FIRSTTIX_EMAIL = os.environ.get("FIRSTTIX_EMAIL", "ryan.sua.rn@gmail.com")
FIRSTTIX_PASSWORD = os.environ.get("FIRSTTIX_PASSWORD", "")

# ---------------------------------------------------------------------------
# Configuration — Email
# ---------------------------------------------------------------------------
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "rsua95@gmail.com")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "rsua95@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
DENYLIST_FILE = SCRIPT_DIR / "denylist.txt"
OUTPUT_FILE = SCRIPT_DIR / "firsttix_shows.json"
LOG_FILE = SCRIPT_DIR / "firsttix.log"
NOTIFIED_FILE = SCRIPT_DIR / "notified_shows.json"
HISTORY_FILE = SCRIPT_DIR / "show_history.json"

# ---------------------------------------------------------------------------
# Rare show detection
# ---------------------------------------------------------------------------
RARE_THRESHOLD_DAYS = 30
RARE_THRESHOLD_COUNT = 3

# ---------------------------------------------------------------------------
# Denylist Gist
# ---------------------------------------------------------------------------
DENYLIST_GIST_RAW_URL = "https://gist.githubusercontent.com/suacide24/f1bf569e229cf1319137a4230d7db1b6/raw/denylist.txt"
DENYLIST_GIST_EDIT_URL = (
    "https://gist.github.com/suacide24/f1bf569e229cf1319137a4230d7db1b6/edit"
)

# GitHub Pages URL (update after setting up the repo)
AVAILABLE_SHOWS_URL = "https://suacide24.github.io/firsttix-checker/"

# ---------------------------------------------------------------------------
# San Diego area — cities within ~45 min of Talmadge
# ---------------------------------------------------------------------------
ALLOWED_CITIES = {
    # San Diego proper & neighborhoods
    "san diego", "talmadge", "kensington", "city heights", "north park",
    "hillcrest", "mission hills", "university heights", "normal heights",
    "la jolla", "pacific beach", "mission beach", "ocean beach", "point loma",
    "clairemont", "mira mesa", "scripps ranch", "tierrasanta", "san carlos",
    "del cerro", "college area", "rolando", "oak park", "encanto",
    "paradise hills", "skyline", "lincoln park", "barrio logan",
    "logan heights", "golden hill", "south park", "north park",
    "gaslamp", "gaslamp quarter", "east village", "little italy",
    "downtown san diego", "downtown", "old town", "midway district",
    "bay park", "bay ho", "linda vista", "serra mesa", "mission valley",
    "fashion valley", "rancho bernardo", "carmel mountain", "sabre springs",
    "rancho penasquitos", "torrey pines", "university city", "sorrento valley",
    "otay ranch", "otay mesa", "san ysidro", "nestor", "bay terraces",
    # South county
    "chula vista", "national city", "coronado", "imperial beach",
    "bonita", "lemon grove", "spring valley", "san marcos",
    # East county
    "la mesa", "el cajon", "santee", "lakeside", "alpine", "ramona",
    # North county coastal
    "del mar", "solana beach", "encinitas", "leucadia", "cardiff",
    "carlsbad", "oceanside",
    # North county inland
    "escondido", "poway", "rancho santa fe", "vista", "san marcos",
    "fallbrook",
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log_message(message: str):
    """Log a message with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(LOG_FILE, "a") as f:
        f.write(log_entry + "\n")


# ---------------------------------------------------------------------------
# User agent rotation & anti-bot helpers
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
]


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def random_delay(min_seconds: float = 2.0, max_seconds: float = 8.0, silent: bool = False):
    if args.fast:
        return
    delay = random.uniform(min_seconds, max_seconds)
    if not silent:
        log_message(f"Waiting {delay:.1f} seconds...")
    time.sleep(delay)


def random_page_delay():
    if args.fast:
        return
    if random.random() < 0.15:
        delay = random.uniform(4.0, 8.0)
    else:
        delay = random.uniform(1.0, 4.0)
    time.sleep(delay)


def create_session_with_random_ua() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    return session


# ---------------------------------------------------------------------------
# Denylist
# ---------------------------------------------------------------------------
def load_denylist() -> set:
    """Load the denylist from GitHub Gist, falling back to local file."""
    denylist = set()

    try:
        log_message("Fetching denylist from Gist...")
        response = requests.get(DENYLIST_GIST_RAW_URL, timeout=10)
        response.raise_for_status()

        for line in response.text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                denylist.add(line.lower())

        log_message(f"Loaded {len(denylist)} shows from Gist denylist")
        return denylist

    except requests.RequestException as e:
        log_message(f"Failed to fetch Gist denylist: {e}")
        log_message("Falling back to local denylist file...")

    if not DENYLIST_FILE.exists():
        log_message("No local denylist file found, creating empty one")
        DENYLIST_FILE.touch()
        return set()

    with open(DENYLIST_FILE, "r") as f:
        denylist = {
            line.strip().lower()
            for line in f
            if line.strip() and not line.startswith("#")
        }

    log_message(f"Loaded {len(denylist)} shows from local denylist")
    return denylist


# ---------------------------------------------------------------------------
# Notification tracking
# ---------------------------------------------------------------------------
def load_notified_shows() -> set:
    if not NOTIFIED_FILE.exists():
        return set()
    try:
        with open(NOTIFIED_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("notified", []))
    except (json.JSONDecodeError, IOError):
        return set()


def save_notified_shows(notified: set):
    with open(NOTIFIED_FILE, "w") as f:
        json.dump({"notified": list(notified)}, f, indent=2)


# ---------------------------------------------------------------------------
# Show history (rare detection)
# ---------------------------------------------------------------------------
def load_show_history() -> dict:
    if not HISTORY_FILE.exists():
        return {"shows": {}}
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"shows": {}}


def save_show_history(history: dict):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def get_show_name_key(show: dict) -> str:
    name = show.get("name", "").strip().lower()
    source = show.get("source", "").strip()
    return f"{source}|{name}"


def update_show_history(shows: list, history: dict) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    for show in shows:
        key = get_show_name_key(show)
        if key not in history["shows"]:
            history["shows"][key] = {
                "name": show.get("name", ""),
                "source": show.get("source", ""),
                "appearances": [],
            }
        if today not in history["shows"][key]["appearances"]:
            history["shows"][key]["appearances"].append(today)
    return history


def is_rare_show(show: dict, history: dict) -> bool:
    key = get_show_name_key(show)
    if key not in history["shows"]:
        return True
    cutoff_date = datetime.now() - timedelta(days=RARE_THRESHOLD_DAYS)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
    appearances = history["shows"][key]["appearances"]
    recent_count = sum(1 for date in appearances if date >= cutoff_str)
    return recent_count < RARE_THRESHOLD_COUNT


def mark_rare_shows(shows: list, history: dict) -> list:
    for show in shows:
        show["rare"] = is_rare_show(show, history)
    return shows


def cleanup_old_history(history: dict, max_age_days: int = 90) -> dict:
    cutoff_date = datetime.now() - timedelta(days=max_age_days)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
    for key in history["shows"]:
        history["shows"][key]["appearances"] = [
            date for date in history["shows"][key]["appearances"] if date >= cutoff_str
        ]
    history["shows"] = {
        key: data for key, data in history["shows"].items() if data["appearances"]
    }
    return history


# ---------------------------------------------------------------------------
# Show helpers
# ---------------------------------------------------------------------------
def get_show_key(show: dict) -> str:
    name = show.get("name", "").strip()
    date = show.get("date", "").strip()
    source = show.get("source", "").strip()
    return f"{source}|{name}|{date}"


def get_chatgpt_link(show: dict) -> str:
    name = show.get("name", "Unknown")
    date = show.get("date", "")
    prompt = f"I'm considering going to see '{name}' in San Diego"
    if date:
        prompt += f" on {date}"
    prompt += ". Is this show good? What can you tell me about it? Should I go see it? What should I expect?"
    return f"https://chat.openai.com/?q={quote(prompt)}"


def find_new_shows(shows: list, notified: set) -> list:
    new_shows = []
    for show in shows:
        key = get_show_key(show)
        if key not in notified:
            new_shows.append(show)
    return new_shows


def group_shows_by_name(shows: list) -> list:
    grouped = {}
    for show in shows:
        key = f"{show.get('source', 'Unknown')}|{show.get('name', 'Unknown')}"
        if key not in grouped:
            grouped[key] = {
                "name": show.get("name", "Unknown"),
                "source": show.get("source", "Unknown"),
                "image": show.get("image"),
                "rare": show.get("rare", False),
                "time_slots": [],
            }
        grouped[key]["time_slots"].append(
            {"date": show.get("date", "N/A"), "link": show.get("link", "")}
        )
        if show.get("rare"):
            grouped[key]["rare"] = True
    return sorted(grouped.values(), key=lambda x: x["name"].lower())


def filter_shows(shows: list, denylist: set) -> list:
    filtered = []
    for show in shows:
        show_name_lower = show.get("name", "").lower()
        is_denied = any(denied in show_name_lower for denied in denylist)
        if not is_denied:
            filtered.append(show)
        else:
            log_message(f"Filtered out (denylist): {show.get('name')}")
    return filtered


# ---------------------------------------------------------------------------
# Geographic filter — San Diego area
# ---------------------------------------------------------------------------
def filter_by_location(shows: list) -> list:
    """Keep only shows whose venue/location matches a city in the San Diego area."""
    filtered = []
    for show in shows:
        location = show.get("location", "").lower()
        venue = show.get("venue", "").lower()
        name = show.get("name", "").lower()
        combined = f"{location} {venue} {name}"

        matched = any(city in combined for city in ALLOWED_CITIES)
        if matched:
            filtered.append(show)
        else:
            log_message(
                f"Filtered out (location): {show.get('name')} — location='{show.get('location', '')}' venue='{show.get('venue', '')}'"
            )
    return filtered


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------
def send_email_notification(new_shows: list) -> bool:
    if not new_shows:
        return True

    if not SMTP_PASSWORD:
        log_message("SMTP_PASSWORD not set - skipping email notification")
        return False

    try:
        grouped_shows = group_shows_by_name(new_shows)
        total_slots = len(new_shows)

        subject = f"🎭 1stTix Alert: {len(grouped_shows)} New Show(s) Available! ({total_slots} time slots)"

        html_body = """
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
        <div style="background: linear-gradient(135deg, #27ae60, #1e8449); padding: 20px; text-align: center;">
            <h1 style="color: white; margin: 0;">🎭 New 1stTix Shows — San Diego!</h1>
            <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">"""
        html_body += f"{len(grouped_shows)} show(s) • {total_slots} time slot(s)"
        html_body += """</p>
        </div>
        <div style="padding: 20px;">
        """

        for show in grouped_shows:
            name = show["name"]
            is_rare = show["rare"]
            time_slots = show["time_slots"]

            rare_badge = (
                '<span style="background: linear-gradient(135deg, #e74c3c, #c0392b); color: white; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px; font-weight: bold;">🔥 RARE</span>'
                if is_rare
                else ""
            )

            chatgpt_link = get_chatgpt_link(show)

            html_body += f"""
            <div style="background: #f8f9fa; border-radius: 8px; padding: 15px; margin-bottom: 15px; border-left: 4px solid #27ae60;">
                <div style="margin-bottom: 10px;">
                    <span style="background: #27ae60; color: white; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: bold; text-transform: uppercase;">1stTix</span>
                    {rare_badge}
                </div>
                <h2 style="margin: 0 0 12px 0; color: #333; font-size: 18px;">{name}</h2>
                <div style="margin-bottom: 12px;">
                    <div style="color: #e67e22; font-size: 13px; font-weight: 500; margin-bottom: 8px;">📅 Available Times ({len(time_slots)})</div>
                    <div style="display: flex; flex-wrap: wrap; gap: 8px;">
            """

            for slot in time_slots:
                date = slot["date"]
                link = slot["link"]
                if link:
                    html_body += f'<a href="{link}" style="display: inline-block; background: rgba(39,174,96,0.1); border: 1px solid rgba(39,174,96,0.3); color: #1e8449; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 13px;">🎟️ {date}</a>'
                else:
                    html_body += f'<span style="display: inline-block; background: #eee; color: #666; padding: 6px 12px; border-radius: 6px; font-size: 13px;">{date}</span>'

            html_body += f"""
                    </div>
                </div>
                <div>
                    <a href="{chatgpt_link}" style="color: #666; font-size: 12px; text-decoration: none;">🤖 Ask AI about this show</a>
                </div>
            </div>
            """

        html_body += f"""
        </div>
        <div style="padding: 20px; background: #f8f9fa; text-align: center; border-top: 1px solid #eee;">
            <a href="{AVAILABLE_SHOWS_URL}" style="display: inline-block; background: #27ae60; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500; margin-right: 10px;">📋 View All Shows</a>
            <a href="{DENYLIST_GIST_EDIT_URL}" style="display: inline-block; background: #6c757d; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500;">✏️ Edit Denylist</a>
        </div>
        <div style="padding: 15px; text-align: center; color: #999; font-size: 11px;">
            Automated message from 1stTix Checker — San Diego
        </div>
        </div>
        </body>
        </html>
        """

        text_body = f"🎭 New 1stTix Shows — San Diego!\n"
        text_body += f"{len(grouped_shows)} show(s) • {total_slots} time slot(s)\n"
        text_body += "=" * 40 + "\n\n"

        for show in grouped_shows:
            name = show["name"]
            is_rare = show["rare"]
            time_slots = show["time_slots"]
            rare_text = " 🔥 RARE" if is_rare else ""

            text_body += f"[1stTix] {name}{rare_text}\n"
            text_body += f"  📅 {len(time_slots)} time slot(s):\n"
            for slot in time_slots:
                date = slot["date"]
                link = slot["link"]
                text_body += f"    • {date}"
                if link:
                    text_body += f"\n      {link}"
                text_body += "\n"
            text_body += f"  🤖 Ask AI: {get_chatgpt_link(show)}\n\n"

        text_body += f"\n📋 View All Shows: {AVAILABLE_SHOWS_URL}\n"
        text_body += f"✏️ Edit Denylist: {DENYLIST_GIST_EDIT_URL}\n"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_EMAIL
        msg["To"] = NOTIFICATION_EMAIL

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, NOTIFICATION_EMAIL, msg.as_string())

        log_message(f"Email sent successfully to {NOTIFICATION_EMAIL}")
        return True

    except Exception as e:
        log_message(f"Failed to send email: {e}")
        return False


# ---------------------------------------------------------------------------
# 1stTix login
# ---------------------------------------------------------------------------
def login_firsttix(session: requests.Session) -> bool:
    """Log into 1sttix.org and return True if successful."""
    try:
        if not FIRSTTIX_PASSWORD:
            log_message("[1stTix] FIRSTTIX_PASSWORD not set - cannot login")
            return False

        response = session.get(FIRSTTIX_LOGIN_URL)
        response.raise_for_status()

        login_data = {
            "email": FIRSTTIX_EMAIL,
            "password": FIRSTTIX_PASSWORD,
        }

        response = session.post(FIRSTTIX_LOGIN_URL, data=login_data, allow_redirects=True)
        response.raise_for_status()

        response_lower = response.text.lower()

        if (
            "email address or password was incorrect" in response_lower
            or "invalid credentials" in response_lower
            or "login failed" in response_lower
            or "attempts left" in response_lower
        ):
            log_message("[1stTix] Login failed - incorrect email or password")
            return False

        if response.url.rstrip("/") == FIRSTTIX_LOGIN_URL.rstrip("/"):
            soup = BeautifulSoup(response.text, "html.parser")
            alerts = soup.find_all("div", class_=["alert", "alert-danger"])
            for alert in alerts:
                alert_text = alert.get_text(strip=True).lower()
                if "incorrect" in alert_text or "invalid" in alert_text or "failed" in alert_text:
                    log_message(f"[1stTix] Login failed: {alert.get_text(strip=True)}")
                    return False

        if (
            "/tixer/" in response.url
            or "welcome" in response.url.lower()
            or "dashboard" in response.url.lower()
        ):
            log_message("[1stTix] Successfully logged in")
            return True

        test_response = session.get(FIRSTTIX_EVENTS_URL)
        test_lower = test_response.text.lower()

        if "must be logged in" in test_lower or "you must be logged in" in test_lower:
            log_message("[1stTix] Login failed - session not authenticated")
            return False

        soup = BeautifulSoup(test_response.text, "html.parser")
        events = soup.find_all("div", class_="event")
        if len(events) > 0:
            log_message(f"[1stTix] Successfully logged in (found {len(events)} events)")
            return True

        title = soup.find("title")
        if title and "important message" not in title.get_text().lower():
            log_message("[1stTix] Successfully logged in")
            return True

        log_message("[1stTix] Login may have failed - could not verify session")
        return False

    except requests.RequestException as e:
        log_message(f"[1stTix] Login request failed: {e}")
        return False


# ---------------------------------------------------------------------------
# 1stTix show fetcher
# ---------------------------------------------------------------------------
def fetch_firsttix_shows(session: requests.Session) -> list:
    """Fetch the list of available shows from 1stTix (all pages)."""
    try:
        shows = []

        sponsor_patterns = [
            "tactical", "coursera", "courses", "certs", "degrees",
            "sponsor", "donate", "discount", "coupon", "hotel",
            "free courses", "cooperator", "5.11",
        ]

        page = 1
        max_pages = 20

        while page <= max_pages:
            url = f"{FIRSTTIX_EVENTS_URL}?page={page}"
            response = session.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            events = soup.find_all("div", class_="event")

            if not events:
                break

            log_message(f"[1stTix] Fetching page {page} ({len(events)} events)...")

            for event in events:
                show_info = {"source": "1stTix"}

                # Get show name from image alt or entry-title
                img = event.find("img")
                if img and img.get("alt"):
                    show_info["name"] = img.get("alt")

                if not show_info.get("name"):
                    title = event.find("div", class_="entry-title")
                    if title:
                        show_info["name"] = title.get_text(strip=True)

                # Get date/time from entry-meta
                meta = event.find("div", class_="entry-meta")
                if meta:
                    meta_text = meta.get_text(" ", strip=True)
                    date_match = re.search(r"(\w{3},\s*\d+\s+\w+\s+'\d+)", meta_text)
                    time_match = re.search(r"(\d{1,2}:\d{2}\s*[AP]M)", meta_text)
                    if date_match:
                        show_info["date"] = date_match.group(1)
                        if time_match:
                            show_info["date"] += " " + time_match.group(1)

                # Extract location / venue from event text
                # Try entry-meta for location info and any venue-related elements
                location_text = ""
                venue_text = ""

                # Check for dedicated venue/location elements
                venue_elem = event.find(
                    "div", class_=lambda c: c and any(
                        x in (c if isinstance(c, str) else " ".join(c))
                        for x in ["venue", "location", "place", "address"]
                    )
                )
                if venue_elem:
                    venue_text = venue_elem.get_text(strip=True)

                # Also grab all text from the event for location matching
                event_text = event.get_text(" ", strip=True)
                location_text = event_text

                show_info["location"] = location_text
                show_info["venue"] = venue_text

                # Get link to event
                link_elem = event.find("a", href=lambda x: x and "get-tickets/event" in x)
                if link_elem:
                    show_info["link"] = link_elem.get("href", "")

                # Get image URL
                if img and img.get("src"):
                    show_info["image"] = img.get("src")

                # Only add if we have a name
                if show_info.get("name"):
                    name_lower = show_info["name"].lower()

                    is_sponsor = any(pattern in name_lower for pattern in sponsor_patterns)
                    has_event_link = bool(show_info.get("link"))
                    has_date = bool(show_info.get("date"))

                    if is_sponsor:
                        log_message(f"[1stTix] Skipping sponsor/ad: {show_info['name']}")
                    elif not has_event_link or not has_date:
                        log_message(
                            f"[1stTix] Skipping non-event (no link/date): {show_info['name']}"
                        )
                    else:
                        shows.append(show_info)

            page += 1
            if page <= max_pages:
                random_page_delay()

        log_message(f"[1stTix] Found {len(shows)} shows total across {page - 1} pages")
        return shows

    except requests.RequestException as e:
        log_message(f"[1stTix] Failed to fetch shows: {e}")
        return []


# ---------------------------------------------------------------------------
# Save shows
# ---------------------------------------------------------------------------
def save_shows(shows: list, scrape_successful: bool = False):
    """Save shows to the JSON file."""
    pt_now = get_pacific_time()
    timestamp = pt_now.strftime("%Y-%m-%dT%H:%M:%S PT")

    existing_last_successful_run = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r") as f:
                existing_data = json.load(f)
                existing_last_successful_run = existing_data.get("last_successful_run")
        except (json.JSONDecodeError, IOError):
            pass

    last_successful_run = existing_last_successful_run
    if scrape_successful:
        last_successful_run = timestamp

    output = {
        "source": "1stTix",
        "last_updated": timestamp,
        "last_successful_run": last_successful_run,
        "count": len(shows),
        "shows": shows,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    log_message(f"Saved {len(shows)} shows to {OUTPUT_FILE.name}")


# ---------------------------------------------------------------------------
# Git push
# ---------------------------------------------------------------------------
def push_to_github():
    """Commit and push updated show data to GitHub for GitHub Pages."""
    import subprocess

    try:
        os.chdir(SCRIPT_DIR)

        data_files = [
            "firsttix_shows.json",
            "notified_shows.json",
            "show_history.json",
        ]
        for data_file in data_files:
            subprocess.run(["git", "add", data_file], capture_output=True)

        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"], capture_output=True
        )
        if result.returncode == 0:
            log_message("[GitHub] No changes to data files, skipping push")
            return True

        commit_msg = (
            f"Update 1stTix shows - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg], check=True, capture_output=True
        )

        stash_result = subprocess.run(
            ["git", "stash", "--include-untracked"], capture_output=True, text=True
        )
        did_stash = "No local changes" not in (stash_result.stdout or "")

        subprocess.run(
            ["git", "pull", "--rebase", "-X", "theirs"], check=True, capture_output=True
        )

        if did_stash:
            subprocess.run(["git", "stash", "pop"], capture_output=True)

        subprocess.run(["git", "push"], check=True, capture_output=True)

        log_message("[GitHub] Successfully pushed show data to GitHub")
        return True

    except subprocess.CalledProcessError as e:
        log_message(f"[GitHub] Failed to push to GitHub: {e}")
        if e.stderr:
            log_message(
                f"[GitHub] Error: {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}"
            )
        return False
    except Exception as e:
        log_message(f"[GitHub] Unexpected error: {e}")
        return False


# ---------------------------------------------------------------------------
# macOS notification
# ---------------------------------------------------------------------------
def notify_user(shows: list):
    if shows:
        show_names = ", ".join(s.get("name", "Unknown")[:30] for s in shows[:3])
        message = f"{len(shows)} shows available: {show_names}..."
    else:
        message = "No shows available (or all filtered)"

    os.system(
        f"""osascript -e 'display notification "{message}" with title "1stTix Checker"' """
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log_message("=" * 50)
    log_message("Starting 1stTix Checker — San Diego")

    # Load denylist
    denylist = load_denylist()

    # Load previously notified shows
    notified_shows = load_notified_shows()
    log_message(f"Loaded {len(notified_shows)} previously notified show+date combinations")

    # Create session
    session = create_session_with_random_ua()
    log_message(f"Using User-Agent: {session.headers.get('User-Agent', '')[:50]}...")

    # Random initial delay
    random_delay(1.0, 5.0)

    # Login and fetch
    log_message("--- Checking 1stTix ---")
    raw_shows = []
    if login_firsttix(session):
        random_delay(2.0, 6.0)
        raw_shows = fetch_firsttix_shows(session)
    else:
        log_message("[1stTix] Failed to login, preserving existing shows")

    log_message(f"Total shows fetched: {len(raw_shows)}")

    # Filter by San Diego area location
    location_filtered = filter_by_location(raw_shows)
    log_message(f"{len(location_filtered)} shows after location filter (San Diego area)")

    # Filter by denylist
    filtered_shows = filter_shows(location_filtered, denylist)
    log_message(f"{len(filtered_shows)} shows after denylist filter")

    # Rare detection
    show_history = load_show_history()
    show_history = update_show_history(filtered_shows, show_history)
    show_history = cleanup_old_history(show_history)
    save_show_history(show_history)

    filtered_shows = mark_rare_shows(filtered_shows, show_history)
    rare_count = sum(1 for s in filtered_shows if s.get("rare"))
    log_message(f"{rare_count} rare shows detected")

    # Save results
    if raw_shows is not None:
        # Strip internal location/venue fields before saving to JSON
        save_list = []
        for s in filtered_shows:
            clean = {k: v for k, v in s.items() if k not in ("location", "venue")}
            save_list.append(clean)
        save_shows(save_list, scrape_successful=len(raw_shows) >= 1)

    # Push to GitHub
    push_to_github()

    # Notifications
    new_shows = find_new_shows(filtered_shows, notified_shows)
    log_message(f"{len(new_shows)} new shows to notify about")

    if new_shows:
        send_email_notification(new_shows)
        notify_user(new_shows)

        for show in new_shows:
            notified_shows.add(get_show_key(show))
        save_notified_shows(notified_shows)
        log_message(f"Marked {len(new_shows)} shows as notified")

        print("\n--- NEW Shows (Just Notified) ---")
        for show in new_shows:
            print(f"  🆕 [1stTix] {show.get('name', 'Unknown')}")
            if show.get("date"):
                print(f"     Date: {show['date']}")
            if show.get("link"):
                print(f"     Link: {show['link']}")
            print()
    else:
        log_message("No new shows to notify about")
        print("\n--- No New Shows ---")
        print("All available shows have already been notified.")

    print(f"\n--- All Available Shows ({len(filtered_shows)} total) ---")
    for show in filtered_shows:
        key = get_show_key(show)
        status = "✓" if key in notified_shows else "🆕"
        print(f"  {status} [1stTix] {show.get('name', 'Unknown')} - {show.get('date', 'N/A')}")

    log_message("Checker completed successfully")


if __name__ == "__main__":
    main()
