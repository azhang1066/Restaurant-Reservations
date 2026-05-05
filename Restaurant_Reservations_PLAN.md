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
- **Notification deduplication** via a `notified_slots` table (not a JSON file); re-notifies if a slot disappears and reappears
- **Deep links** built in `deep_links.py`, validated with a 2-second HEAD request before sending, falling back to homepage if unreachable
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
- `app/app.py` — REST API (restaurants CRUD, settings, logs, resolve-url, deep-link, test-notification)
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
- Replaced `seen_slots.json` file tracking and deleted the file; CLI `main.py` path now uses the same SQLite table as the Flask scheduler
- Log states: ✅ sent · 🔁 skipped · 🔍 nothing found · ❌ failed

### Stage 5 — Deep Link Booking URLs ✅
- `deep_links.py` — `build_booking_url(platform, venue, slot) → {web_url, app_url, fallback_url}`
- HEAD validation (2 s timeout) on every candidate URL; falls back to restaurant homepage on failure/timeout
- Resy format: `resy.com/venues/{slug}/{venue_id}?date=YYYY-MM-DD&seats=N` (slug derived from restaurant name)
- OpenTable format: `opentable.com/r/{rid}?covers=N&dateTime=YYYY-MM-DDTHH:MM`
- No public native app scheme found for either platform; `app_url == web_url`
- ntfy: `Click` header = `web_url`; `Actions` header would add "Open App" if `app_url` ever differs
- Pushover: `url` = `web_url`, `url_title` = "Book Now"
- Activity log entries with a URL show a **Book Now →** pill link in the dashboard
- Each watchlist card has a **Test link** button → calls `/api/restaurants/{id}/deep-link` and opens in new tab
- CLI: `python deep_links.py --platform resy --venue-id 12345 --venue-name "Carbone" --date 2026-05-09 --time 20:00 --party-size 2`

### Stage 6 — End-to-End Testing & Hardening 🔲
- Live test with a real Resy and OpenTable restaurant
- Verify Resy deep link format resolves correctly (the slug-based URL is reverse-engineered)
- Consider storing `resy_url` or `resy_slug` in the restaurant record if HEAD validation falls back too often
- Add unit tests for `deep_links.py` and `notifiers/`
- ~~Prune old `seen_slots.json` reference / delete the file~~ ✅
- Fix dashboard status pill (currently stuck on "Loading…")

### Stage 7 — Dashboard UX Polish 🔲
- "Check Now" button to trigger an immediate availability run from the UI
- ~~Log auto-pruning (keep last 500 entries)~~ ✅
- ~~Scheduler status indicator (last check time, next check time)~~ ✅
- Availability count badge on watchlist cards
- *Design note: consult a design-focused tool for layout/visual decisions before building*

### Stage 8 — Multi-Party-Size Support ✅
- `party_sizes TEXT` column already existed in the DB schema (JSON array, e.g. `"[4, 2]"`); backward compat via `_row_to_restaurant` fallback was already in place
- `app/notifier.py` — Added `notified_this_run: set` (scoped per `check_restaurant()` call) to deduplicate across sizes: if a slot's `(date, time)` fires for size 4, size 2 skips it with a "larger party already notified" debug log. Email batch now uses `actually_notified` instead of all `new_slots`.
- `app/app.py` — Added `_validate_party_sizes()` helper; both POST and PUT endpoints return 400 if `party_sizes` is empty, non-list, or contains values outside 1–20
- `notifiers/base.py` — Notification body updated to "Table for N" (was "N guests")
- `static/app.js` — Replaced `normalizePartySizes` text-input approach with a `ChipInput` class; chips show ordinal labels (1st/2nd/3rd), up/down reorder buttons disabled at boundaries, × remove; add form and every card edit panel use the class; form reset calls `setValues([])`
- `templates/index.html` — Party sizes text input replaced with `<div id="party-sizes-chips" class="chip-input-container">`
- `static/style.css` — Added chip styles (`.chip-input-container`, `.chip`, `.chip-ordinal`, `.chip-value`, `.chip-btn`, `.chip-input-wrap`, `.chip-text-input`)

---

## Completed This Session

**Session date:** 2026-05-04

### Scheduler status pill (Stage 7 / Priority 2)
- Added `last_check_time: datetime | None` module-level variable to `app/notifier.py`; set to `datetime.now(timezone.utc)` at the end of every `run_check()` call
- Added `GET /api/status` endpoint in `app/app.py` returning `{last_check, next_check, restaurant_count}`; `next_check` computed as `last_check + CHECK_INTERVAL_MINUTES`
- Added `loadStatus()` in `static/app.js`; formats the `#status-pill` as "Last check: X min ago · Next: Y min"; called on init and every 30 s alongside the existing log refresh

---

## Previous Session

**Session date:** 2026-05-02

### CLI deduplication cleanup (Priority 2)
- Replaced `load_seen_slots`/`save_seen_slots`/`get_seen_slot_key` in `main.py` with `db.has_notified_slot()`, `db.add_notified_slot()`, `db.remove_stale_notified_slots()`
- Removed `import json`, `SEEN_SLOTS_FILE` constant, and the three file-based helpers from `main.py`
- `check_restaurant()` signature simplified (no `seen_slots` param); `run_check()` calls `db.init_db()` on startup
- CLI and Flask scheduler now share the same `notified_slots` SQLite table
- Deleted `seen_slots.json` from the repo

### Activity log pruning (Priority 4)
- Added a `DELETE … NOT IN … LIMIT 500` prune query inside `add_activity_log()` in `app/db.py`; table is capped at 500 rows on every insert

### Multi-party-size support (Stage 8)
- Cross-size deduplication in `app/notifier.py`: `notified_this_run` set prevents a slot at the same date+time from firing notifications for both a larger and smaller party size in the same check run
- API validation in `app/app.py`: `party_sizes` must be a non-empty list of integers 1–20; enforced on both create and update
- Notification body updated to "Table for N" in `notifiers/base.py`
- Chip-style party size input in dashboard: `ChipInput` class in `app.js` replaces the old comma-separated text field; chips are orderable via ↑/↓ buttons and removable with ×; ordinal hint labels (1st/2nd/3rd) shown on each chip; works in both the Add Restaurant form and every card edit panel

---

## Previous Session

**Session date:** 2026-05-01

### Push notification abstraction (Stage 3)
- Created `notifiers/` package: `base.py` (ABC + `format_slot_body()`), `ntfy.py`, `pushover.py`, `__init__.py`
- Added `notified_slots` table to SQLite; replaced `seen_slots.json` deduplication logic
- Refactored `app/notifier.py`: per-slot push, batched email, ✅🔁🔍❌ log states
- Updated `app/app.py`: new settings keys, NTFY_TOPIC auto-generation, `/api/test-notification` endpoint
- Updated settings panel UI: provider dropdown, ntfy subscribe link with copy button, Pushover fields, Email/Push toggles, test notification button
- Added `--test-notify` CLI flag to `main.py`
- Updated `requirements.txt` (added `httpx>=0.27.0`), `.env.example`, `README.md`

### Deep link booking URLs (Stage 5)
- Created `deep_links.py` with `build_booking_url()`, `_validate_url()` (HEAD, 2 s timeout), and standalone CLI
- Updated `notifiers/base.py`: `send()` now accepts `urls: dict` instead of a string; body appends "— tap to book"
- Updated `notifiers/ntfy.py` and `notifiers/pushover.py` to use `urls["web_url"]`
- Added `url TEXT` column to `activity_log` (backward-compatible ALTER TABLE)
- Updated `add_activity_log()` to accept optional `url=` kwarg
- Updated `app/notifier.py` to call `build_booking_url()` per slot and store URL in log
- Added `/api/restaurants/<id>/deep-link` endpoint to `app/app.py`
- Updated `static/app.js`: "Book Now →" link on log entries, "Test link" button on restaurant cards
- Updated `static/style.css`: `.book-now-link` pill style
- Updated `README.md` with "Deep Link Booking URLs" section and CLI examples

---

## Next Actions

These are ready to pick up immediately in the next session with no additional context required.

### Priority 1 — Verify Resy deep link format
The Resy URL `resy.com/venues/{slug}/{venue_id}?date=...&seats=...` is reverse-engineered from `lookup_venue.py` output, not confirmed against a live browser session.

**Steps:**
1. Add a real Resy restaurant to the watchlist via the dashboard URL resolver
2. Click the **Test link** button on that restaurant card; observe what URL opens and whether it pre-fills date/party size correctly
3. If the URL 404s or redirects to the homepage, investigate:
   - Option A: Add a `resy_slug` TEXT column to the `restaurants` table and parse it from the URL in `lookup_venue.py`'s `parse_resy_url()` (returns slug in `path_parts[1]` already — just needs to be stored)
   - Option B: Use `resy.com/cities/{city}/venues/{slug}` format (requires storing city too)
4. Update `deep_links._resy_candidate()` with the confirmed format

### Priority 2 — "Check Now" button
Allow triggering an immediate availability check from the dashboard without waiting for the scheduler interval.

**Steps:**
1. Add `POST /api/check-now` endpoint in `app/app.py` that calls `run_check()` in a background thread (to avoid blocking the HTTP response)
2. Add a **Check Now** button to the dashboard header in `templates/index.html`
3. Wire it in `static/app.js`: POST to `/api/check-now`, show a brief "Checking…" state, then refresh logs and status after 3 s
