# Restaurant Reservations Plan

## Overview

A self-hosted Python/Flask application that monitors Resy and OpenTable for available reservation slots and delivers real-time push and email notifications with one-tap booking deep links. The user manages a watchlist of restaurants (with per-day time windows and party sizes) from a web dashboard on their local network. When a matching slot appears, a push notification fires immediately with a pre-filled URL that drops the user into the booking confirmation screen before the slot disappears.

**Stack:** Python 3.11+, Flask, SQLite, `schedule`, `httpx`, `requests`, `python-dotenv`  
**Push providers:** ntfy (default, free, no account) · Pushover (alternative)  
**Booking platforms:** Resy · OpenTable  
**Run:** `python -m app` or `python run_dashboard.py` → http://localhost:5000

---

## General Work Plan

The project is built as a single Python package (`app/`) with a Flask web server that:
1. Serves the management dashboard (add/edit/delete restaurants, notification settings, live activity log)
2. Spawns a background daemon thread running `schedule` to check API availability on a configurable interval (default 20 min)
3. Sends push notifications via an abstracted `notifiers/` package and email via SMTP when new slots are found

Key architectural decisions:
- **SQLite only** — no external database; `restaurants.db` holds all state
- **Notification deduplication** via a `notified_slots` table; re-notifies if a slot disappears and reappears
- **Deep links** built in `deep_links.py`, validated with a 2-second HEAD request before sending, falling back to venue homepage if unreachable
- **Provider abstraction** — `NOTIFY_PROVIDER=ntfy|pushover` env var selects the active push implementation with zero code changes
- **Settings in `.env`** — all credentials/toggles written by the dashboard UI to `.env` via `_save_env()`

---

## Implementation Stages

### Stage 1 — Core Monitoring Engine ✅
- `main.py` — CLI entry point with `--test` and `--test-notify` flags
- `resy_api.py` — `ResyAPIClient`, `OpenTableAPIClient`, `TimeSlot` dataclass
- `restaurants.py` — static config (migrated to DB; kept for backward compat)
- `lookup_venue.py` — Resy/OpenTable URL parser + name-based venue search

### Stage 2 — Flask Dashboard ✅
- `app/app.py` — REST API (restaurants CRUD, settings, logs, resolve-url, deep-link, test-notification, check-now, status)
- `app/db.py` — SQLite layer: `restaurants`, `activity_log`, `notified_slots` tables
- `app/notifier.py` — background scheduler, `check_restaurant()`, per-slot push + batch email
- `templates/index.html` — 4-panel dashboard: Add Restaurant / Watchlist / Activity Log / Notification Settings
- `static/app.js` — all frontend logic (no framework)
- `static/style.css` — dark theme

### Stage 3 — Mobile Push Notifications ✅
- `notifiers/` package: `BaseNotifier` ABC, `NtfyNotifier`, `PushoverNotifier`, `get_notifier()` factory
- Provider selected via `NOTIFY_PROVIDER` env var; defaults to ntfy
- ntfy: POST to `ntfy.sh/{topic}` — high priority, fork_and_knife tag, Click URL
- Pushover: POST to api.pushover.net — priority 1, url/url_title fields
- Settings UI: provider dropdown, ntfy topic with subscribe link + copy button, Pushover fields, Email/Push toggles, "Send test notification" button
- `NTFY_TOPIC` auto-generated on first dashboard load and persisted to `.env`

### Stage 4 — Smart Notification Deduplication ✅
- `notified_slots` SQLite table: `(venue_id, date, time, party_size)` composite PK
- `has_notified_slot()`, `add_notified_slot()`, `remove_stale_notified_slots()` in `db.py`
- Stale removal: slots no longer in the API response are evicted → re-notified if they return
- Replaced `seen_slots.json` file tracking; CLI `main.py` and Flask scheduler share the same SQLite table
- Log states: ✅ sent · 🔁 skipped · 🔍 nothing found · ❌ failed

### Stage 5 — Deep Link Booking URLs ✅
- `deep_links.py` — `build_booking_url(platform, venue, slot) → {web_url, app_url, fallback_url}`
- HEAD validation (2 s timeout) on every candidate URL; falls back to venue homepage on failure/timeout
- Confirmed URL formats:
  - Resy: `resy.com/cities/{city}/venues/{slug}?date=YYYY-MM-DD&seats=N`
  - OpenTable: `opentable.com/r/{slug}?covers=N&dateTime=YYYY-MM-DDTHH:MM`
- `resy_slug`, `resy_city`, `opentable_slug` stored in the `restaurants` table so deep links are faithful to the original URL
- No public native app scheme found for either platform; `app_url == web_url`
- ntfy: `Click` header = `web_url`; Pushover: `url` = `web_url`, `url_title` = "Book Now"
- Activity log entries with a URL show a **Book Now →** pill link in the dashboard
- Each watchlist card has a **Test link** button → calls `/api/restaurants/{id}/deep-link` and opens in new tab
- CLI: `python deep_links.py --platform resy --venue-slug j-bespoke --venue-city new-york-ny --date 2026-05-09 --time 20:00 --party-size 2`

### Stage 6 — URL Resolution & Venue ID Lookup ✅
- `lookup_venue.parse_resy_url()` returns 4-tuple `(venue_id, venue_name, slug, city)`; handles `/cities/{city}/venues/{slug}` (current), `/venues/{slug}/{id}` (old), `/venues/{id}` (legacy)
- `lookup_venue.parse_opentable_url()` returns 3-tuple `(restaurant_id, restaurant_name, slug)`; handles `/r/{slug}` (current) and `/r/{slug}/r{id}` (old)
- `ResyAPIClient.get_venue_id_from_slug(slug, city)` — two-strategy lookup:
  - **Primary**: `GET /3/venue?location_id={id}&url_slug={slug}` using `_LOCATION_IDS` dict (confirmed: `new-york-ny → 1`)
  - **Fallback**: `GET /3/search` with lat/lng coordinates, matching by `url_slug`; `_CITY_COORDS` covers 15 common cities
- `resolve_url` endpoint auto-fetches venue ID when Resy credentials are configured; result auto-populates the dashboard form

### Stage 7 — Dashboard UX Polish ✅
- "Check Now" button — triggers immediate check from UI; shows "Checking…"; prevents overlapping runs with `_check_running` flag
- Scheduler status pill — shows time since last check and minutes until next; updates every 30 s
- Activity log auto-pruned to 500 entries
- Availability count badge on watchlist cards 🔲

### Stage 8 — Multi-Party-Size Support ✅
- `party_sizes TEXT` column (JSON array, e.g. `"[4, 2]"`); backward compat via `_row_to_restaurant` fallback
- Cross-size deduplication in `app/notifier.py`: `notified_this_run` set prevents duplicate notifications for the same slot across sizes in one check run
- API validation: `party_sizes` must be a non-empty list of integers 1–20
- Chip-style party size UI: ordinal labels (1st/2nd/3rd), ↑/↓ reorder, × remove

---

## Completed This Session

**Session date:** 2026-05-04

### Resy & OpenTable URL parsing
- `parse_resy_url()` updated to 4-tuple; correctly parses current `/cities/{city}/venues/{slug}` format
- `parse_opentable_url()` updated to 3-tuple; correctly parses current `/r/{slug}` format (no numeric ID)
- Both parsers preserve the raw slug to avoid lossy name→slug round-trips

### Deep link URL format corrections
- **Resy**: corrected from `/venues/{slug}/{venue_id}` to `/cities/{city}/venues/{slug}?date=...&seats=...`
- **OpenTable**: corrected from `/r/{rid}?...` to `/r/{slug}?covers=...&dateTime=...`
- `resy_slug`, `resy_city`, `opentable_slug` columns added to `restaurants` table (ALTER TABLE migrations); all CRUD wired through; frontend captures and sends all three at add-time

### Resy venue ID auto-lookup
- `ResyAPIClient.get_venue_id_from_slug(slug, city)` added to `resy_api.py`
- Primary path: `GET /3/venue?location_id={id}&url_slug={slug}` (confirmed `new-york-ny → 1`)
- Fallback path: coordinate-based search via `GET /3/search`, matches by `url_slug`
- Wired into `/api/resolve-url` — pasting a Resy URL auto-populates venue ID if credentials are set

### Dashboard UX (Stage 7)
- Check Now button with overlap protection
- Scheduler status pill (last check / next check)

---

## Previous Sessions

**Session date:** 2026-05-02

- CLI deduplication unified with Flask scheduler (both use `notified_slots` SQLite table)
- Activity log pruned to 500 entries on every insert
- Multi-party-size chip UI; cross-size deduplication in notifier; API validation

**Session date:** 2026-05-01

- Push notification abstraction (`notifiers/` package, ntfy + Pushover)
- Deep link system (`deep_links.py`, HEAD validation, Book Now UI, Test link button)

---

## Next Actions

### Priority 1 — Availability count badge (Stage 7)
Add a small badge to each watchlist card showing the number of available slots found in the last check. Requires storing the latest slot count per restaurant (e.g. a `last_slot_count` column or in-memory dict) and surfacing it via the `/api/restaurants` response.

### Priority 2 — Expand Resy location_id mapping
`_LOCATION_IDS` in `resy_api.py` currently only has `new-york-ny → 1`. For each new city, check browser DevTools on resy.com to find the `location_id` used in `/3/venue` requests, then add it to the dict.

### Priority 3 — End-to-end live test
Run a full check cycle with a real Resy and OpenTable restaurant; verify:
- Availability API returns slots
- Deep links open the correct pre-filled booking page
- Push notifications fire and the tap target URL is correct
- Deduplication suppresses repeat notifications correctly

### Priority 4 — Unit tests
Add tests for `deep_links.py` (URL construction, fallback logic) and `notifiers/` (send payloads).
