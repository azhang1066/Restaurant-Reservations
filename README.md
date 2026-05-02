# Restaurant Reservation Notifier

Automated Python application to monitor Resy and OpenTable for restaurant availability and send real-time notifications via email and Pushover.

## Features

✨ **Multi-Platform Support**
- Monitor both Resy and OpenTable restaurants
- Add multiple restaurants with different search criteria

📧 **Flexible Notifications**
- Email notifications (SMTP)
- Pushover mobile/desktop notifications
- Dual channel support (sends via both when available)

⏰ **Smart Scheduling**
- Background monitoring on configurable intervals
- Avoids duplicate notifications for same slots
- Single-check test mode for debugging

🎯 **Advanced Filtering**
- Filter by party size
- Filter by days of week
- Filter by preferred time range
- Persistent state tracking

## Architecture

The application is built with a modular design:

- **`main.py`** - Main scheduler and notification engine
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

### 4. Pushover (Optional)

1. Sign up at [pushover.net](https://pushover.net)
2. Create an application for this script
3. Copy your user key and application token

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
| `PUSHOVER_TOKEN` | Pushover application token | No |
| `PUSHOVER_USER` | Pushover user key | No |

## Usage

```bash
# Run normally (checks every 20 minutes by default)
python main.py

# Run a single check immediately without scheduling
python main.py --test

# Check logs
tail -f notifier.log
```

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

Edit `restaurants.py` to add restaurants you want to monitor:

```python
RESTAURANTS = [
    # Resy restaurant example
    {
        "name": "Carbone",
        "source": "resy",
        "resy_venue_id": "1234567",
        "party_size": 2,
        "days": ["Friday", "Saturday"],
        "time_range": ("18:00", "22:00"),  # Optional: filter by time
    },
    # OpenTable restaurant example
    {
        "name": "The Spotted Pig",
        "source": "opentable",
        "opentable_rid": "12345",
        "party_size": 4,
        "days": ["Friday", "Saturday", "Sunday"],
        # time_range is optional
    },
]
```

### Configuration Options

| Option | Required | Description | Example |
|--------|----------|-------------|---------|
| `name` | Yes | Restaurant name | "Carbone" |
| `source` | No | "resy" or "opentable" | "resy" |
| `resy_venue_id` | If source="resy" | Resy venue ID | "1234567" |
| `opentable_rid` | If source="opentable" | OpenTable restaurant ID | "12345" |
| `party_size` | Yes | Number of guests | 2, 3, 4, etc. |
| `days` | Yes | Days to check (full names) | ["Friday", "Saturday"] |
| `time_range` | No | Time window in 24h format | ("18:00", "22:00") |

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