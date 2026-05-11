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
- **Provider abstraction** — active push provider selected via `user_settings.notify_provider` (ntfy or pushover); `get_notifier(settings)` factory accepts a settings dict
- **Split settings storage** — notification settings (provider, topics, SMTP, toggles) live in the `user_settings` DB table; Resy credentials, `AUTO_BOOK`, and `CHECK_INTERVAL_MINUTES` stay in `.env`; dashboard UI reads/writes both transparently

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
- `notifiers/` package: `BaseNotifier` ABC, `NtfyNotifier`, `PushoverNotifier`, `get_notifier(settings)` factory
- Provider selected via `user_settings.notify_provider`; defaults to ntfy
- ntfy: POST to `ntfy.sh/{topic}` — high priority, fork_and_knife tag, Click URL
- Pushover: POST to api.pushover.net — priority 1, url/url_title fields
- Settings UI: provider dropdown, ntfy topic with subscribe link + copy button, Pushover fields, Email/Push toggles, "Send test notification" button
- `NTFY_TOPIC` auto-generated on first dashboard load and persisted to `user_settings` DB table

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
- Availability count badge on watchlist cards ✅

### Stage 8 — Multi-Party-Size Support ✅
- `party_sizes TEXT` column (JSON array, e.g. `"[4, 2]"`); backward compat via `_row_to_restaurant` fallback
- Cross-size deduplication in `app/notifier.py`: `notified_this_run` set prevents duplicate notifications for the same slot across sizes in one check run
- API validation: `party_sizes` must be a non-empty list of integers 1–20
- Chip-style party size UI: ordinal labels (1st/2nd/3rd), ↑/↓ reorder, × remove

### Stage 9 — One-Tap Resy Booking ✅
- **`resy_api.py`** — 5 exception classes (`ResyBookingError`, `ResySlotUnavailableError`, `ResyPaymentError`, `ResyAuthError`, `ResyTimeoutError`); 3 new `ResyAPIClient` methods:
  - `get_booking_details(venue_id, date, time, party_size)` → `GET /3/details`, returns `config_id` + `payment_method_id`; respects `RESY_PAYMENT_METHOD_ID` env override; raises `ResyPaymentError` if no card on file
  - `book_reservation(config_id, payment_method_id)` → `POST /3/book`, returns `resy_token`
  - `cancel_reservation(resy_token)` → `DELETE /3/reservation`
- **`app/db.py`** — `bookings` table (`id, restaurant_id, venue_id, date, time, party_size, resy_token, status, booked_at`) added to both `init_db()` and as migration #6 (idempotent `CREATE TABLE IF NOT EXISTS`); `booking_params TEXT` column added to `activity_log` as migration #7; `add_booking()`, `get_bookings()` (LEFT JOIN for restaurant name), `cancel_booking()` functions added; `add_activity_log()` accepts optional `booking_params` dict; `get_recent_logs()` deserializes it
- **`app/app.py`** — `POST /api/restaurants/<id>/book` (3-step Resy flow, writes to bookings table, structured JSON response); `GET /api/bookings`; `DELETE /api/bookings/<id>` (calls Resy cancel API, updates DB status); `AUTO_BOOK` and `RESY_PAYMENT_METHOD_ID` exposed in settings GET/POST
- **`app/notifier.py`** — module-level `_auto_book_cooldowns: dict[str, float]` + 60-second `_COOLDOWN_SECONDS`; when `AUTO_BOOK=true`: re-calls `/3/details` (fresh slot check), enforces cooldown, attempts booking, pushes "✅ Booked!" on success; falls through to normal notification on any failure (never silent); `booking_params` JSON stored on every Resy slot-found log entry
- **`templates/index.html`** — Bookings panel (5th, full-width); Auto-Book toggle with yellow warning box + `RESY_PAYMENT_METHOD_ID` override field in Notification Settings
- **`static/app.js`** — `bookReservation()` (POST, loading state, toast); `cancelBooking()` (confirm dialog, DELETE); `loadBookings()` (table with status badges and Cancel buttons); `showToast()` (animated corner toast); "Book via Resy" button on log entries with `booking_params`; `loadSettings`/`saveSettings` wired to two new fields; `loadBookings()` called on init and after any book/cancel action
- **`static/style.css`** — bookings table styles, `.status-badge` variants (confirmed/cancelled/failed), `.btn-cancel-booking`, `.btn-book-inline`, `.auto-book-warning`, toast animation

### Stage 10 — Notification Settings in DB (user_settings table) ✅
- **`app/db.py`** — `user_settings` table: `user_id INTEGER PRIMARY KEY` + one column per notification setting; `_USER_SETTINGS_COLUMNS` dict maps env-key names → column names; migration #9; `get_user_settings(user_id=1)` returns a dict keyed by env-var names; `save_user_settings(settings, user_id=1)` uses INSERT OR IGNORE + UPDATE; seeds from `.env` on first run so existing deployments keep their config
- **`app/app.py`** — `_ENV_ONLY_KEYS` constant (`RESY_API_KEY`, `RESY_AUTH_TOKEN`, `AUTO_BOOK`, `RESY_PAYMENT_METHOD_ID`, `CHECK_INTERVAL_MINUTES`); `GET /api/settings` merges DB notification settings with env-only credentials; `POST /api/settings` routes each key to DB or `.env`; `test_notification` reads provider from DB
- **`app/notifier.py`** — `check_restaurant()` calls `db.get_user_settings()` once per run, passes dict to `get_notifier()` and `send_email_notification()`
- **`notifiers/__init__.py`** — `get_notifier(settings)` accepts settings dict, passes to constructors
- **`notifiers/ntfy.py`, `notifiers/pushover.py`** — read credentials from settings dict first; fall back to `os.getenv` for backward compat with `.env`-only deployments
- **`app/availability.py`** — `send_email_notification(restaurant, slots, smtp_settings)` reads SMTP config from settings dict first, env fallback
- `user_id=1` hardcoded throughout; column exists for multi-user wiring later

---

## Completed This Session

**Session date:** 2026-05-10

### Stage 10 — Notification settings to DB (see stage entry above for full detail)

### Stage 9 — One-tap Resy booking (see stage entry above for full detail)
Key decisions:
- Three-call sequence (`/3/details` → `/3/book` → optional `DELETE /3/reservation`) — no calls combined or skipped
- `booking_params` stored as JSON on activity log rows (migration #7) — avoids fragile log-message parsing
- Auto-book cooldown is per `venue_id`, not per slot, to prevent hammering on rapid fluctuations
- Failed auto-book always falls through to normal push notification

### Availability count badge (Stage 7)
- `last_slot_count INTEGER` column added to `restaurants` table (migration #8)
- `set_last_slot_count(restaurant_id, count)` in `db.py`
- `notifier.py` accumulates unique `(date, time)` tuples across all party-size × day combos; calls `set_last_slot_count` at end of each `check_restaurant()` run
- `app.js` — green "N slots" badge when `> 0`, gray "None available" when `0`, no badge before first check

### Help / How To Use page
- `GET /help` route → `templates/help.html`; **Help** nav link added to `index.html`
- Fully static, no JS, mobile-responsive; dark theme via existing CSS variables
- Sticky TOC sidebar + content; collapses to single column on ≤860 px
- Sections: Getting Started · Adding a Restaurant · Notification Setup · Reading the Activity Log · Check Scheduling · Bookings & One-Tap Booking · Deep Links · Tips & Troubleshooting
- **Booking error messages** table in Tips & Troubleshooting

---

## Previous Sessions

**Session date:** 2026-05-07

### Architecture cleanup — threading, schema migrations, N+1 query, file split

**Race condition on `_check_running` globals** (2026-05-07)
- Replaced `_check_running: bool` with `_check_lock = threading.Lock()` in `notifier.py`
- `run_check()` uses `_check_lock.acquire(blocking=False)` + try/finally — atomic, no TOCTOU gap
- Added `is_check_running()` accessor; `app.py` no longer reads private `_notifier._check_running`

**Schema migrations via try/except** (2026-05-07)
- Added `_MIGRATIONS` list and `_run_migrations(conn)` in `db.py`
- `PRAGMA user_version` tracks applied migrations; each runs exactly once
- Fresh DBs: detected via `resy_slug` column presence → stamped to latest, no ALTER TABLE needed
- `activity_log` CREATE TABLE now includes `url TEXT` directly

**N+1 in `remove_stale_notified_slots`** (2026-05-07)
- Replaced SELECT + Python loop with a single `DELETE … WHERE time NOT IN (…)` query
- Empty `current_times` case handled with a bare `DELETE WHERE venue_id/date/party_size`

**`OpenTableAPIClient` moved to `opentable_api.py`** (2026-05-07)
- `OpenTableAPIClient` and `create_opentable_client()` extracted from `resy_api.py` into new `opentable_api.py`
- `app/availability.py` imports `create_opentable_client` from `opentable_api`
- `resy_api.py` docstring updated; `create_resy_client` docstring removed (self-evident)

**Dead `struct_data` in `ResyAPIClient.search_venues`** (2026-05-07)
- Removed `struct_data` dict (built but never sent), `date` and `party_size` parameters (only fed `struct_data`), and the stale docstring

**Non-atomic `_save_env`** (2026-05-07)
- `_save_env` now writes to a temp file via `tempfile.mkstemp` in the same directory, then atomically renames it into place with `Path.replace()`
- Original `.env` is never partially written; temp file is cleaned up on error

**`CHECK_INTERVAL_MINUTES` read directly from env** (2026-05-07)
- Removed `CHECK_INTERVAL_MINUTES` from `restaurants.py` usage in `notifier.py`, `app.py`, and `main.py`
- All three now call `int(os.getenv("CHECK_INTERVAL_MINUTES", 20))` directly
- `import restaurants as restaurant_config` removed from `app.py` (was the only remaining use)

### Architecture cleanup — inverted import, DB init overhead, legacy fields

**Inverted import (app/notifier.py → main.py)**
- Created `app/availability.py` — canonical home for shared business logic: `check_resy_availability`, `check_opentable_availability`, `get_date_for_day`, `filter_slots_by_time`, `send_email_notification`
- `app/notifier.py` now imports from `app.availability` instead of `main`; dependency direction is correct
- `main.py` duplicate definitions removed (~100 lines); imports from `app.availability` like any other consumer

**`init_db()` called on every database operation**
- All 11 per-function `conn = init_db()` calls in `db.py` replaced with `conn = get_connection()`
- Schema setup (DDL) runs only once at startup via the existing `db.init_db()` call in `start_scheduler()`
- Eliminates ~7 unnecessary DDL statements per DB operation; a full check cycle no longer triggers hundreds of `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` round-trips

**Legacy `time_earliest`/`time_latest` fields**
- Added one-time data migration in `init_db()`: any rows carrying `time_earliest`/`time_latest` but no `time_ranges` are promoted to `time_ranges` format on startup
- `_row_to_restaurant` compat block removed; returned dict no longer includes the old fields
- `add_restaurant` INSERT and `update_restaurant` UPDATE no longer write those columns (13 columns instead of 15)
- `ensure_migrated` converts the legacy static config's `time_range` tuple directly to `time_ranges` dict
- `app.py` create/update endpoint handlers cleaned of both fields
- Columns remain in the SQLite schema (safe); only the read/write paths are gone

---

## Previous Sessions

**Session date:** 2026-05-05

### Resy location_id auto-discovery
- `_auto_discover_location_id(slug, city)` — probes location_ids 1–30 on `/3/venue`, updates `_LOCATION_IDS` in-place, logs paste-ready hint for permanent storage
- `_lookup_by_search` now accepts `city`; kicks off `_auto_discover_location_id` in a daemon thread after the first successful coordinate-based lookup for an unmapped city
- `discover_all_location_ids()` — batch discovers every city in `_CITY_COORDS`; logs a full paste-ready `_LOCATION_IDS` block
- CLI: `python main.py --discover-locations` (requires valid credentials; Resy auth token expires periodically)
- README updated with new CLI flag and a "Resy City Location IDs" section

**Session date:** 2026-05-04

- `parse_resy_url()` updated to 4-tuple; correctly parses current `/cities/{city}/venues/{slug}` format
- `parse_opentable_url()` updated to 3-tuple; correctly parses current `/r/{slug}` format (no numeric ID)
- Resy deep link corrected to `/cities/{city}/venues/{slug}?date=...&seats=...`
- OpenTable deep link corrected to `/r/{slug}?covers=...&dateTime=...`
- `resy_slug`, `resy_city`, `opentable_slug` columns added to `restaurants` table; CRUD and frontend wired through
- `ResyAPIClient.get_venue_id_from_slug(slug, city)` with primary (location_id) + fallback (coordinate search) strategies
- `/api/resolve-url` auto-populates venue ID when credentials are set
- Check Now button with overlap protection; scheduler status pill (last/next check)

**Session date:** 2026-05-02

- CLI deduplication unified with Flask scheduler (both use `notified_slots` SQLite table)
- Activity log pruned to 500 entries on every insert
- Multi-party-size chip UI; cross-size deduplication in notifier; API validation

**Session date:** 2026-05-01

- Push notification abstraction (`notifiers/` package, ntfy + Pushover)
- Deep link system (`deep_links.py`, HEAD validation, Book Now UI, Test link button)

---

## Next Actions

### Priority 1 — Multi-user wiring
Wire `user_id` from Flask session/auth context into `get_user_settings()` / `save_user_settings()` once auth is added (currently hardcoded to 1).

### Priority 2 — End-to-end live test of booking flow
Run a full cycle with a real Resy restaurant that has open slots and verify:
- `GET /3/details` returns a valid `config_id` and `payment_method_id`
- `POST /3/book` completes and returns a `resy_token`
- Booking appears in the Bookings panel with status `confirmed`
- Cancel button calls `DELETE /3/reservation` and updates status to `cancelled`
- Auto-book fires correctly with `AUTO_BOOK=true` and the cooldown is respected
- Failed booking falls through to normal push notification

### Priority 3 — Unit tests
Add tests for:
- `resy_api.py` booking methods (mock HTTP responses for `/3/details`, `/3/book`, `/3/reservation`)
- `deep_links.py` URL construction and fallback logic
- `notifiers/` send payloads
- `db.get_user_settings()` / `db.save_user_settings()` round-trip
