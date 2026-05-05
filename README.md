# Restaurant Reservation Notifier

Automated Python application to monitor Resy and OpenTable for restaurant availability and send real-time notifications via push and email. Monitors a priority-ordered list of party sizes per restaurant — if a table for 4 opens you get notified immediately; if only a table for 2 is available, that fires instead without duplicating the alert.

## Features

✨ **Multi-Platform Support**
- Monitor both Resy and OpenTable restaurants
- Add multiple restaurants with different search criteria

📧 **Flexible Notifications**
- Mobile push via **ntfy** (free, no account required)
- Mobile push via **Pushover** (alternative)
- Email notifications (SMTP)
- Per-channel on/off toggles
- Smart deduplication — re-notifies only if a slot disappeared and came back
- **Deep link booking** — notifications tap straight into the pre-filled booking flow

⏰ **Smart Scheduling**
- Background monitoring on configurable intervals
- Avoids duplicate notifications for same slots
- Single-check test mode for debugging

🎯 **Advanced Filtering**
- Priority-ordered party sizes — check for a table of 4 first, fall back to 2 if unavailable; no duplicate notifications for the same slot
- Filter by days of week
- Per-day time windows (e.g. Friday 6–9 pm, Saturday 7–10 pm)
- Persistent state tracking — re-notifies only if a slot disappears and reappears

## Architecture

The application is built with a modular design:

- **`main.py`** - Main scheduler and notification engine
- **`deep_links.py`** - Booking URL builder with HEAD validation and CLI
- **`resy_api.py`** - Clean API client for Resy and OpenTable
- **`restaurants.py`** - Restaurant configuration and constants
- **`.env.example`** - Environment variable template

### API Module (`resy_api.py`)

The new `resy_api.py` module provides:
- `ResyAPIClient` - Handles Resy API interactions
- `OpenTableAPIClient` - Handles OpenTable API interactions
- `TimeSlot` - Data class representing available reservation slots
- Better error handling and logging
- Factory functions for client creation

## Requirements

```
requests>=2.31.0
python-dotenv>=1.0.0
schedule>=1.2.0
```

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

### 1. Environment Setup

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

### 2. Resy Credentials

To get your Resy API key and auth token:

1. Visit [resy.com](https://resy.com) and log in
2. Open Developer Tools (`F12`)
3. Go to **Application** → **Cookies** → look for `authToken` (the long JWT starting with `eyJ...`)
4. Also check **Network** tab → search for `api.resy.com` requests → check headers for `x-resy-auth-token`

### 3. Email Configuration

For Gmail:
1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Select "Mail" and "Windows Computer" (or your device)
3. Generate an app password
4. Use this password in `SMTP_PASS`

For other email providers, use your SMTP credentials.

### 4. Push Notifications

#### ntfy (Default — Free, No Account)

ntfy is a free, open-source push notification service.

1. Install the **ntfy** app on your phone:
   - iOS: [ntfy on the App Store](https://apps.apple.com/app/ntfy/id1625396347)
   - Android: [ntfy on Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy) or [F-Droid](https://f-droid.org/packages/io.heckel.ntfy/)
2. Open the dashboard at `http://localhost:5000` and go to **Notification Settings**
3. Your topic (e.g., `resy-notifier-a8f3k2`) is auto-generated — copy the subscribe link shown next to it
4. In the ntfy app, tap **+** and subscribe to the topic URL shown (e.g., `ntfy.sh/resy-notifier-a8f3k2`)
5. Click **Send test notification** in the dashboard to confirm it works

The topic acts as a private channel — anyone with the exact URL can receive messages, so keep it secret.

#### Pushover (Alternative)

1. Sign up at [pushover.net](https://pushover.net)
2. Create an application for this script
3. Copy your **User Key** and **App Token** into the dashboard settings (or `.env`)
4. Set `NOTIFY_PROVIDER=pushover` in `.env` or select Pushover in the dashboard

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `RESY_API_KEY` | Resy API key from browser | Yes |
| `RESY_AUTH_TOKEN` | Resy auth token from browser | Yes |
| `SMTP_HOST` | SMTP server (e.g., smtp.gmail.com) | Yes |
| `SMTP_PORT` | SMTP port (usually 587 for TLS) | Yes |
| `SMTP_USER` | Email account username | Yes |
| `SMTP_PASS` | Email account password or app password | Yes |
| `NOTIFY_EMAIL` | Email address to send notifications to | Yes |
| `FROM_EMAIL` | Sender email (optional, defaults to SMTP_USER) | No |
| `NOTIFY_PROVIDER` | `ntfy` or `pushover` (default: `ntfy`) | No |
| `NTFY_TOPIC` | ntfy topic name (auto-generated if empty) | No |
| `PUSHOVER_USER_KEY` | Pushover user key | No |
| `PUSHOVER_APP_TOKEN` | Pushover app token | No |
| `NOTIFY_VIA_PUSH` | Enable push channel (`true`/`false`) | No |
| `NOTIFY_VIA_EMAIL` | Enable email channel (`true`/`false`) | No |
| `PUSHOVER_TOKEN` | Legacy Pushover token (standalone main.py) | No |
| `PUSHOVER_USER` | Legacy Pushover user (standalone main.py) | No |

## Usage

```bash
# Run normally (checks every 20 minutes by default)
python main.py

# Run a single check immediately without scheduling
python main.py --test

# Send a test push notification and exit
python main.py --test-notify

# Check logs
tail -f notifier.log
```

## Web Dashboard

A lightweight dashboard is available for managing restaurants and notification settings.

```bash
python run_dashboard.py
```

Or run it as a package:

```bash
python -m app
```

Open the dashboard in your browser at:

- `http://localhost:5000`

If you want to access the dashboard from another device on the same WiFi:

1. Find your computer's local IP address.
2. Open `http://<your-computer-ip>:5000` on the phone or tablet.

Example:

```bash
http://192.168.1.18:5000
```

The dashboard includes:

- restaurant watchlist management (add by URL, edit, enable/disable, delete)
- priority-ordered party sizes — chip-style input where each chip shows its priority order (1st, 2nd…); reorder with ↑/↓, remove with ×
- per-day time windows (e.g. Friday 6–9 pm only)
- live activity log with availability events and **Book Now →** deep links
- push and email notification configuration
- scheduler status pill — shows time since last check and minutes until the next one (updates every 30 s)
- **Check Now** button — triggers an immediate availability check without waiting for the scheduler; shows "Checking…" and refreshes the log and status pill when done

## Deep Link Booking URLs

When a matching slot is found, the push notification and the activity log both include a pre-filled booking URL that drops you directly into the reservation flow — no manual date/time/party-size selection required.

### How it works

1. The notifier calls `deep_links.build_booking_url(platform, venue, slot)` for every new slot.
2. A lightweight HEAD request (2 s timeout) validates the URL resolves correctly. If validation fails or times out, it falls back to the restaurant's homepage so the notification is never delayed.
3. The validated URL is used as the `Click` target in ntfy, the `url` field in Pushover, and stored in the activity log so you can also click **Book Now →** directly from the dashboard.

### URL formats (as-inspected)

| Platform | Deep link format |
|---|---|
| Resy | `resy.com/venues/{slug}/{venue_id}?date=YYYY-MM-DD&seats=N` |
| OpenTable | `opentable.com/r/{rid}?covers=N&dateTime=YYYY-MM-DDTHH:MM` |

Resy pre-fills **date and party size** (no time parameter in the web URL — the slot grid opens to the right date).  
OpenTable pre-fills **date, time, and party size** via the `dateTime` parameter.

### Native app deep links

Neither Resy nor OpenTable publicly documents a `resy://` or `opentable://` URL scheme, so `app_url` is the same as `web_url` for both platforms. If a native scheme is ever confirmed, set it in `deep_links.py` and the ntfy notifier will automatically add an "Open App" action button.

### If URLs break after a platform update

Platforms occasionally restructure their URLs. If the HEAD validation starts returning fallback URLs for all slots, check `deep_links.py` and update `_resy_candidate()` or `_opentable_candidate()` to match the new format. Use the CLI to test without running the full scheduler:

```bash
python deep_links.py --platform resy --venue-id 12345 --venue-name "Carbone" \
    --date 2026-05-09 --time 20:00 --party-size 2

python deep_links.py --platform opentable --venue-id 67890 --venue-name "Nobu" \
    --date 2026-05-09 --time 19:30 --party-size 4 --no-validate
```

You can also click **Test link** on any restaurant card in the dashboard to open a sample booking URL for today in your browser.

## Venue ID Lookup Utility

Use the `lookup_venue.py` script to easily find Resy and OpenTable venue IDs:

```bash
# Search Resy by restaurant name and city
python lookup_venue.py "Carbone" "New York" --resy

# Search both platforms
python lookup_venue.py "Nobu" "Los Angeles" --both

# Parse venue ID directly from Resy URL
python lookup_venue.py --resy-url "https://resy.com/venues/carbone/12345"

# Parse restaurant ID from OpenTable URL
python lookup_venue.py --opentable-url "https://opentable.com/r/carbone/r12345"
```

The utility supports:
- **Name + City Search**: Finds venues by restaurant name and location
- **URL Parsing**: Extracts IDs directly from Resy/OpenTable URLs
- **Multi-Platform**: Search both Resy and OpenTable simultaneously
- **Detailed Results**: Shows venue names, neighborhoods, cuisines, and direct booking URLs

## Restaurant Configuration

The recommended way to manage restaurants is through the web dashboard (URL resolver auto-fills the venue ID). For scripted/bulk setup you can also edit `restaurants.py` directly:

```python
RESTAURANTS = [
    # Resy — check for 4 first, fall back to 2
    {
        "name": "Carbone",
        "source": "resy",
        "resy_venue_id": "1234567",
        "party_sizes": [4, 2],          # priority order: 4 preferred, 2 as fallback
        "days": ["Friday", "Saturday"],
        "time_range": ("18:00", "22:00"),
    },
    # OpenTable — single size is fine too
    {
        "name": "The Spotted Pig",
        "source": "opentable",
        "opentable_rid": "12345",
        "party_sizes": [2],
        "days": ["Friday", "Saturday", "Sunday"],
    },
]
```

### Configuration Options

| Option | Required | Description | Example |
|--------|----------|-------------|---------|
| `name` | Yes | Restaurant name | `"Carbone"` |
| `source` | Yes | `"resy"` or `"opentable"` | `"resy"` |
| `resy_venue_id` | If source="resy" | Resy venue ID | `"1234567"` |
| `opentable_rid` | If source="opentable" | OpenTable restaurant ID | `"12345"` |
| `party_sizes` | Yes | Priority-ordered list of party sizes (1–20) | `[4, 2]` |
| `days` | Yes | Days to check (full names) | `["Friday", "Saturday"]` |
| `time_range` | No | Time window in 24h format | `("18:00", "22:00")` |

`party_sizes` is checked in order: the scheduler queries the API for each size and fires a notification as soon as a match is found, skipping smaller sizes for any slot that already triggered an alert for a larger size.

### Finding Restaurant IDs

**Easy Method**: Use the `lookup_venue.py` utility script:

```bash
# For Resy restaurants
python lookup_venue.py "Carbone" "New York" --resy

# For OpenTable restaurants (use URL parsing)
python lookup_venue.py --opentable-url "https://opentable.com/r/carbone/r12345"
```

**Manual Methods** (if you prefer):

#### Finding Resy Venue IDs

**Method 1: From URL**
1. Go to the restaurant's Resy page
2. The URL format is: `https://resy.com/venues/{VENUE_ID}/{RESTAURANT_NAME}`
3. Extract the numeric ID

**Method 2: From API**
1. Open [resy.com](https://resy.com) and search for restaurant
2. Click on a restaurant
3. Open Developer Tools (F12) → Network tab
4. Look for requests to `api.resy.com`
5. In the response JSON, find the `id` field

#### Finding OpenTable Restaurant IDs

**Method 1: From URL**
1. Go to OpenTable, find the restaurant
2. The URL format is: `https://opentable.com/r/{RESTAURANT_NAME}/{ID}`
3. Extract the numeric ID at the end

**Method 2: From API**
1. Open Developer Tools → Network tab
2. Search for the restaurant
3. Find requests to `platform.opentable.com`
4. The restaurant ID should be in the URL or response

## API Module

The `resy_api.py` module provides clean abstractions for API interactions:

```python
from resy_api import create_resy_client, create_opentable_client

# Get Resy client
resy = create_resy_client()
slots = resy.get_availability(venue_id="1234567", party_size=2, date="2024-01-15")

# Get OpenTable client
opentable = create_opentable_client()
slots = opentable.get_availability(restaurant_id="12345", party_size=2, date="2024-01-15")

# TimeSlot objects have these attributes
for slot in slots:
    print(f"{slot.datetime} at {slot.time}")
```

## Deployment

### Render (Free)

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Set environment variables in Render dashboard
4. Deploy

### Railway

1. Create a new project on Railway
2. Add your GitHub repository
3. Set environment variables
4. Deploy

## Logs

Logs are written to `notifier.log` with timestamps for all checks and findings.