# Restaurant Reservation Notifier

Automated Python application to monitor Resy and OpenTable for restaurant availability and send real-time notifications via push and email. Monitors a priority-ordered list of party sizes per restaurant — if a table for 4 opens you get notified immediately; if only a table for 2 is available, that fires instead without duplicating the alert.

## Features

**Multi-Platform Support**
- Monitor both Resy and OpenTable restaurants
- Add restaurants by pasting their URL — venue details auto-resolve

**Flexible Notifications**
- Mobile push via **ntfy** (free, no account required)
- Mobile push via **Pushover** (alternative)
- Email notifications (SMTP)
- Per-channel on/off toggles
- Smart deduplication — re-notifies only if a slot disappeared and came back
- **Deep link booking** — notifications tap straight into the pre-filled booking flow

**Smart Scheduling**
- Background monitoring on configurable intervals (default 20 min)
- **Check Now** button for an immediate on-demand check
- Scheduler status pill — shows time since last check and minutes until the next

**Advanced Filtering**
- Priority-ordered party sizes — check for a table of 4 first, fall back to 2 if unavailable; no duplicate notifications for the same slot
- Filter by days of week
- Per-day time windows (e.g. Friday 6–9 pm, Saturday 7–10 pm)
- Persistent state tracking — re-notifies only if a slot disappears and reappears

## Architecture

```
app/
  app.py            Flask REST API (CRUD, settings, resolve-url, deep-link, check-now, status)
  availability.py   Shared business logic — availability checks, time filtering, date helpers, email
  db.py             SQLite layer — restaurants, activity_log, notified_slots tables
  notifier.py       Background scheduler, check_restaurant(), push + email dispatch
notifiers/
  base.py        BaseNotifier ABC + slot body formatter
  ntfy.py        ntfy push implementation
  pushover.py    Pushover push implementation
  __init__.py    get_notifier() factory
templates/
  index.html     Single-page dashboard
static/
  app.js         All frontend logic (no framework)
  style.css      Dark theme
deep_links.py      Booking URL builder with HEAD validation + CLI
resy_api.py        ResyAPIClient — availability, venue ID lookup, location_id auto-discovery
opentable_api.py   OpenTableAPIClient — availability checks
lookup_venue.py    URL parser for Resy and OpenTable restaurant URLs
restaurants.py   Static config (legacy; superseded by SQLite)
main.py          CLI entry point (--test, --test-notify, --discover-locations)
```

## Requirements

```
requests>=2.31.0
httpx>=0.27.0
python-dotenv>=1.0.0
schedule>=1.2.0
flask>=3.0.0
```

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
# Run the dashboard (recommended)
python run_dashboard.py
# or
python -m app
```

Open `http://localhost:5000` in your browser. The dashboard starts the background scheduler automatically.

To access from another device on the same network, use your computer's local IP:

```
http://192.168.1.x:5000
```

## Configuration

All settings are managed from the dashboard's **Notification Settings** panel and written to `.env`. You can also edit `.env` directly — copy `.env.example` to get started:

```bash
cp .env.example .env
```

### Resy Credentials

Required for availability monitoring. To get them:

1. Open [resy.com](https://resy.com) and log in
2. Open DevTools → **Network** tab
3. Make any request (e.g. search for a restaurant)
4. Click any request to `api.resy.com` and inspect its headers:
   - `Authorization: ResyAPI api_key=...` → value is `RESY_API_KEY`
   - `x-resy-auth-token: ...` → value is `RESY_AUTH_TOKEN`

Enter these in the dashboard settings panel, or set them in `.env`:

```
RESY_API_KEY=your_api_key
RESY_AUTH_TOKEN=your_auth_token
```

When credentials are configured, pasting a Resy URL in the dashboard automatically resolves the numeric venue ID needed for monitoring.

### Push Notifications

#### ntfy (Default — Free, No Account)

1. Install the **ntfy** app on your phone (iOS / Android)
2. Open the dashboard → **Notification Settings**
3. Your topic (e.g. `resy-notifier-a8f3k2`) is auto-generated — copy the subscribe link
4. In the ntfy app, tap **+** and paste the subscribe link
5. Click **Send test notification** to confirm

The topic is a private channel — keep it secret.

#### Pushover (Alternative)

1. Sign up at [pushover.net](https://pushover.net) and create an application
2. Enter your **User Key** and **App Token** in the dashboard settings
3. Select **Pushover** in the provider dropdown

### Email

For Gmail, generate an [App Password](https://myaccount.google.com/apppasswords) and use it as `SMTP_PASS`. For other providers use your standard SMTP credentials.

### Environment Variables

| Variable | Description | Required |
|---|---|---|
| `RESY_API_KEY` | Resy API key (from browser DevTools) | For Resy monitoring |
| `RESY_AUTH_TOKEN` | Resy auth token (from browser DevTools) | For Resy monitoring |
| `SMTP_HOST` | SMTP server (e.g. `smtp.gmail.com`) | For email |
| `SMTP_PORT` | SMTP port (usually `587`) | For email |
| `SMTP_USER` | Email account username | For email |
| `SMTP_PASS` | Email password or app password | For email |
| `NOTIFY_EMAIL` | Recipient email address | For email |
| `FROM_EMAIL` | Sender address (defaults to `SMTP_USER`) | No |
| `NOTIFY_PROVIDER` | `ntfy` or `pushover` (default: `ntfy`) | No |
| `NTFY_TOPIC` | ntfy topic (auto-generated if blank) | No |
| `PUSHOVER_USER_KEY` | Pushover user key | For Pushover |
| `PUSHOVER_APP_TOKEN` | Pushover app token | For Pushover |
| `NOTIFY_VIA_PUSH` | Enable push channel (`true`/`false`) | No |
| `NOTIFY_VIA_EMAIL` | Enable email channel (`true`/`false`) | No |
| `CHECK_INTERVAL_MINUTES` | How often to poll for availability (default: `20`) | No |

## Adding Restaurants

The recommended workflow is through the dashboard:

1. Go to the restaurant's page on Resy or OpenTable
2. Copy the URL and paste it into the **Add Restaurant** form
3. Click **Resolve URL** — the name, city, and slug are filled automatically; if Resy credentials are configured the numeric venue ID is also fetched automatically
4. Set your party sizes (priority-ordered chips), days, and time windows
5. Click **Add Restaurant**

### Party Sizes

Party sizes are priority-ordered: the scheduler checks the first size, and only moves to the next if no slot was found. A slot that triggers a notification for a larger size is suppressed for smaller sizes in the same run.

Use the chip input to add sizes and drag them into priority order with ↑/↓.

### Per-Day Time Windows

Each selected day can have its own time window. Leave a window blank to accept any time.

## Deep Link Booking URLs

When a matching slot is found, the push notification and the activity log both include a pre-filled booking URL that drops you directly into the reservation flow.

### URL formats

| Platform | Deep link format |
|---|---|
| Resy | `resy.com/cities/{city}/venues/{slug}?date=YYYY-MM-DD&seats=N` |
| OpenTable | `opentable.com/r/{slug}?covers=N&dateTime=YYYY-MM-DDTHH:MM` |

A lightweight HEAD request (2 s timeout) validates every URL before sending. If it fails or times out, the notification falls back to the venue homepage so you're never left without a link.

Click **Test link** on any watchlist card to open a sample booking URL for today in your browser.

### CLI (testing without the scheduler)

```bash
python deep_links.py --platform resy \
    --venue-slug j-bespoke --venue-city new-york-ny \
    --date 2026-05-09 --time 20:00 --party-size 2

python deep_links.py --platform opentable \
    --venue-slug soothr-new-york \
    --date 2026-05-09 --time 19:30 --party-size 4 --no-validate
```

## CLI Usage

```bash
# Run a single availability check and exit
python main.py --test

# Send a test push notification and exit
python main.py --test-notify

# Discover Resy location_ids for all supported cities (requires valid credentials)
python main.py --discover-locations

# Parse venue details from a URL
python lookup_venue.py --resy-url "https://resy.com/cities/new-york-ny/venues/j-bespoke"
python lookup_venue.py --opentable-url "https://www.opentable.com/r/soothr-new-york"

# Tail the log
tail -f notifier.log
```

## Finding Venue IDs Manually

The dashboard URL resolver handles this automatically. If you need IDs manually:

**Resy:** The numeric venue ID is not in the web URL. Get it from the Resy API:
1. Open DevTools → Network on a Resy venue page
2. Find the request to `api.resy.com/3/venue?...` — the `id` in the response is the venue ID

**OpenTable:** The restaurant slug is in the URL path (`/r/{slug}`). The numeric ID (if needed for the monitoring API) appears in requests to `platform.opentable.com`.

## Resy City Location IDs

Resy's venue lookup API requires a numeric `location_id` for the city. `new-york-ny` is hardcoded as `1`; other cities use a coordinate-based search fallback. To promote a city to the faster primary path:

1. Ensure valid Resy credentials are set in `.env`
2. Run `python main.py --discover-locations`
3. The log prints a ready-to-paste `_LOCATION_IDS` block — copy it into `resy_api.py`

Auto-discovery also runs automatically in the background the first time any venue in an unmapped city is looked up. The discovered ID is cached for the lifetime of the process and logged so you can make it permanent.

## Logs

Activity is written to both `notifier.log` and the dashboard's live activity log. The log is capped at 500 entries and pruned automatically.
