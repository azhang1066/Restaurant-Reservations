# Restaurant Reservation Notifier

Python script to monitor restaurant availability on Resy and send notifications.

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

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `RESY_API_KEY` | Resy API key | Yes |
| `RESY_AUTH_TOKEN` | Resy auth token | Yes |
| `SMTP_HOST` | SMTP server host | Yes |
| `SMTP_PORT` | SMTP server port | Yes |
| `SMTP_USER` | SMTP username | Yes |
| `SMTP_PASS` | SMTP password | Yes |
| `NOTIFY_EMAIL` | Email to send notifications to | Yes |
| `FROM_EMAIL` | Email to send from (optional, defaults to SMTP_USER) | No |
| `PUSHOVER_TOKEN` | Pushover app token | No |
| `PUSHOVER_USER` | Pushover user key | No |

## Usage

```bash
# Run normally (checks every 20 minutes)
python main.py

# Run a single check immediately (no scheduling)
python main.py --test
```

## Restaurant Configuration

Edit `restaurants.py` to add restaurants you want to monitor:

```python
RESTAURANTS = [
    {
        "name": "Nobu Malibu",
        "resy_venue_id": "1234",
        "party_size": 2,
        "days": ["Friday", "Saturday"],
        "time_range": ("18:00", "22:00"),  # Optional
    },
]
```

### Finding Resy Venue IDs

1. Go to the restaurant's Resy page (e.g., `https://resy.com/venues/nobu-malibu`)
2. Open Developer Tools (F12) → Network tab
3. Look for API requests to `api.resy.com`
4. Find the venue ID in the request URL or response

Or search on Resy and inspect the network traffic.

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