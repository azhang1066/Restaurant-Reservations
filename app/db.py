import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "restaurants.db"

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# Each entry is applied exactly once, in order, identified by its 1-based index.
# PRAGMA user_version tracks how many have been applied so far.
_MIGRATIONS: List[str] = [
    "ALTER TABLE restaurants ADD COLUMN time_ranges TEXT",       # 1
    "ALTER TABLE restaurants ADD COLUMN resy_slug TEXT",         # 2
    "ALTER TABLE restaurants ADD COLUMN resy_city TEXT",         # 3
    "ALTER TABLE restaurants ADD COLUMN opentable_slug TEXT",    # 4
    "ALTER TABLE activity_log ADD COLUMN url TEXT",              # 5
    "CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id INTEGER NOT NULL, venue_id TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, party_size INTEGER NOT NULL, resy_token TEXT, status TEXT NOT NULL DEFAULT 'confirmed', booked_at TEXT NOT NULL)",  # 6
    "ALTER TABLE activity_log ADD COLUMN booking_params TEXT",   # 7
    "ALTER TABLE restaurants ADD COLUMN last_slot_count INTEGER", # 8
    "CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER PRIMARY KEY, notify_provider TEXT, ntfy_topic TEXT, pushover_user_key TEXT, pushover_app_token TEXT, pushover_token TEXT, pushover_user TEXT, smtp_host TEXT, smtp_port TEXT, smtp_user TEXT, smtp_pass TEXT, smtp_from TEXT, smtp_to TEXT, enable_email TEXT, enable_push TEXT)",  # 9
    "ALTER TABLE restaurants ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1",   # 10
    "ALTER TABLE activity_log ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1",  # 11
    "ALTER TABLE bookings ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1",      # 12
    "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)",  # 13
    # Recreate notified_slots with user_id in the composite PK (4 steps)
    "CREATE TABLE IF NOT EXISTS notified_slots_new (user_id INTEGER NOT NULL DEFAULT 1, venue_id TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, party_size INTEGER NOT NULL, notified_at TEXT NOT NULL, PRIMARY KEY (user_id, venue_id, date, time, party_size))",  # 14
    "INSERT OR IGNORE INTO notified_slots_new SELECT 1, venue_id, date, time, party_size, notified_at FROM notified_slots",  # 15
    "DROP TABLE notified_slots",   # 16
    "ALTER TABLE notified_slots_new RENAME TO notified_slots",  # 17
    # Add Resy credential columns to user_settings
    "ALTER TABLE user_settings ADD COLUMN resy_api_key TEXT",              # 18
    "ALTER TABLE user_settings ADD COLUMN resy_auth_token TEXT",           # 19
    "ALTER TABLE user_settings ADD COLUMN auto_book TEXT",                 # 20
    "ALTER TABLE user_settings ADD COLUMN resy_payment_method_id TEXT",   # 21
    "ALTER TABLE user_settings ADD COLUMN check_interval_minutes TEXT",   # 22
]

# Maps the uppercase env-var names used by the API to the lowercase column names
# in the user_settings table.
_USER_SETTINGS_COLUMNS: Dict[str, str] = {
    "NOTIFY_PROVIDER":        "notify_provider",
    "NTFY_TOPIC":             "ntfy_topic",
    "PUSHOVER_USER_KEY":      "pushover_user_key",
    "PUSHOVER_APP_TOKEN":     "pushover_app_token",
    "PUSHOVER_TOKEN":         "pushover_token",
    "PUSHOVER_USER":          "pushover_user",
    "SMTP_HOST":              "smtp_host",
    "SMTP_PORT":              "smtp_port",
    "SMTP_USER":              "smtp_user",
    "SMTP_PASS":              "smtp_pass",
    "FROM_EMAIL":             "smtp_from",
    "NOTIFY_EMAIL":           "smtp_to",
    "NOTIFY_VIA_EMAIL":       "enable_email",
    "NOTIFY_VIA_PUSH":        "enable_push",
    "RESY_API_KEY":           "resy_api_key",
    "RESY_AUTH_TOKEN":        "resy_auth_token",
    "AUTO_BOOK":              "auto_book",
    "RESY_PAYMENT_METHOD_ID": "resy_payment_method_id",
    "CHECK_INTERVAL_MINUTES": "check_interval_minutes",
}


def _run_migrations(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    target = len(_MIGRATIONS)
    if version >= target:
        return
    # Fresh database: CREATE TABLE IF NOT EXISTS already includes every column,
    # so stamp to the latest version without running ALTER TABLE statements.
    if version == 0:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(restaurants)").fetchall()}
        if "user_id" in existing:
            conn.execute(f"PRAGMA user_version = {target}")
            return
    for i, sql in enumerate(_MIGRATIONS, start=1):
        if i > version:
            conn.execute(sql)
            conn.execute(f"PRAGMA user_version = {i}")


def init_db() -> sqlite3.Connection:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS restaurants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                source TEXT NOT NULL,
                resy_venue_id TEXT,
                resy_slug TEXT,
                resy_city TEXT,
                opentable_rid TEXT,
                opentable_slug TEXT,
                party_sizes TEXT NOT NULL,
                days TEXT NOT NULL,
                time_earliest TEXT,
                time_latest TEXT,
                time_ranges TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_slot_count INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                highlight INTEGER NOT NULL DEFAULT 0,
                url TEXT,
                booking_params TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                restaurant_id INTEGER NOT NULL,
                venue_id TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                party_size INTEGER NOT NULL,
                resy_token TEXT,
                status TEXT NOT NULL DEFAULT 'confirmed',
                booked_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notified_slots (
                user_id INTEGER NOT NULL DEFAULT 1,
                venue_id TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                party_size INTEGER NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY (user_id, venue_id, date, time, party_size)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                notify_provider TEXT,
                ntfy_topic TEXT,
                pushover_user_key TEXT,
                pushover_app_token TEXT,
                pushover_token TEXT,
                pushover_user TEXT,
                smtp_host TEXT,
                smtp_port TEXT,
                smtp_user TEXT,
                smtp_pass TEXT,
                smtp_from TEXT,
                smtp_to TEXT,
                enable_email TEXT,
                enable_push TEXT,
                resy_api_key TEXT,
                resy_auth_token TEXT,
                auto_book TEXT,
                resy_payment_method_id TEXT,
                check_interval_minutes TEXT
            )
            """
        )
        _run_migrations(conn)
        # One-time data migration: promote time_earliest/time_latest into time_ranges
        rows = conn.execute(
            "SELECT id, days, time_earliest, time_latest FROM restaurants "
            "WHERE (time_earliest IS NOT NULL OR time_latest IS NOT NULL) "
            "AND (time_ranges IS NULL OR time_ranges = '' OR time_ranges = '[]')"
        ).fetchall()
        for row in rows:
            days = _deserialize_list(row["days"])
            t_earliest, t_latest = row["time_earliest"], row["time_latest"]
            if days and (t_earliest or t_latest):
                conn.execute(
                    "UPDATE restaurants SET time_ranges = ? WHERE id = ?",
                    (json.dumps({day: [t_earliest, t_latest] for day in days}), row["id"]),
                )
    return conn


def _serialize_list(value: Any) -> str:
    if isinstance(value, str):
        try:
            return json.dumps(json.loads(value))
        except Exception:
            return json.dumps([value])
    return json.dumps(value or [])


def _deserialize_list(value: Optional[str]) -> List[Any]:
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return [x.strip() for x in value.split(",") if x.strip()]


def _row_to_restaurant(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "source": row["source"],
        "resy_venue_id": row["resy_venue_id"],
        "resy_slug": row["resy_slug"] if row["resy_slug"] else "",
        "resy_city": row["resy_city"] if row["resy_city"] else "",
        "opentable_rid": row["opentable_rid"],
        "opentable_slug": row["opentable_slug"] if row["opentable_slug"] else "",
        "party_sizes": _deserialize_list(row["party_sizes"]),
        "days": _deserialize_list(row["days"]),
        "time_ranges": _deserialize_list(row["time_ranges"]) if row["time_ranges"] else {},
        "enabled": bool(row["enabled"]),
        "last_slot_count": row["last_slot_count"],
    }


# ---------------------------------------------------------------------------
# User auth
# ---------------------------------------------------------------------------

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    return dict(row) if row else None


def create_user(email: str, password_hash: str) -> int:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    with conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.lower(), password_hash, now),
        )
    return cursor.lastrowid


def get_active_user_ids() -> List[int]:
    """Return distinct user_ids that have at least one enabled restaurant."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM restaurants WHERE enabled = 1"
    ).fetchall()
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------

def get_restaurants(user_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.execute(
        "SELECT * FROM restaurants WHERE user_id = ? ORDER BY id DESC", (user_id,)
    )
    return [_row_to_restaurant(row) for row in cursor.fetchall()]


def get_restaurant(restaurant_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM restaurants WHERE id = ? AND user_id = ?", (restaurant_id, user_id)
    ).fetchone()
    return _row_to_restaurant(row) if row else None


def add_restaurant(restaurant: Dict[str, Any], user_id: int) -> int:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO restaurants (
                user_id, name, source, resy_venue_id, resy_slug, resy_city,
                opentable_rid, opentable_slug,
                party_sizes, days, time_ranges,
                enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                restaurant["name"],
                restaurant["source"],
                restaurant.get("resy_venue_id"),
                restaurant.get("resy_slug") or "",
                restaurant.get("resy_city") or "",
                restaurant.get("opentable_rid"),
                restaurant.get("opentable_slug") or "",
                _serialize_list(restaurant.get("party_sizes", [])),
                _serialize_list(restaurant.get("days", [])),
                _serialize_list(restaurant.get("time_ranges", {})),
                int(restaurant.get("enabled", True)),
                now,
                now,
            ),
        )
    return cursor.lastrowid


def update_restaurant(restaurant_id: int, restaurant: Dict[str, Any], user_id: int) -> bool:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    with conn:
        cursor = conn.execute(
            """
            UPDATE restaurants SET
                name = ?,
                source = ?,
                resy_venue_id = ?,
                resy_slug = ?,
                resy_city = ?,
                opentable_rid = ?,
                opentable_slug = ?,
                party_sizes = ?,
                days = ?,
                time_ranges = ?,
                enabled = ?,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                restaurant["name"],
                restaurant["source"],
                restaurant.get("resy_venue_id"),
                restaurant.get("resy_slug") or "",
                restaurant.get("resy_city") or "",
                restaurant.get("opentable_rid"),
                restaurant.get("opentable_slug") or "",
                _serialize_list(restaurant.get("party_sizes", [])),
                _serialize_list(restaurant.get("days", [])),
                _serialize_list(restaurant.get("time_ranges", {})),
                int(restaurant.get("enabled", True)),
                now,
                restaurant_id,
                user_id,
            ),
        )
    return cursor.rowcount > 0


def delete_restaurant(restaurant_id: int, user_id: int) -> bool:
    conn = get_connection()
    with conn:
        cursor = conn.execute(
            "DELETE FROM restaurants WHERE id = ? AND user_id = ?", (restaurant_id, user_id)
        )
    return cursor.rowcount > 0


def set_last_slot_count(restaurant_id: int, count: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE restaurants SET last_slot_count = ? WHERE id = ?",
            (count, restaurant_id),
        )


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

def add_activity_log(
    message: str,
    level: str = "info",
    highlight: bool = False,
    url: Optional[str] = None,
    booking_params: Optional[Dict[str, Any]] = None,
    user_id: int = 1,
) -> None:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    booking_params_json = json.dumps(booking_params) if booking_params else None
    with conn:
        conn.execute(
            "INSERT INTO activity_log (user_id, timestamp, level, message, highlight, url, booking_params) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, now, level, message, int(highlight), url, booking_params_json),
        )
        conn.execute(
            "DELETE FROM activity_log WHERE user_id = ? AND id NOT IN "
            "(SELECT id FROM activity_log WHERE user_id = ? ORDER BY id DESC LIMIT 500)",
            (user_id, user_id),
        )


def get_recent_logs(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.execute(
        "SELECT timestamp, level, message, highlight, url, booking_params "
        "FROM activity_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = []
    for row in cursor.fetchall():
        d = dict(row)
        if d.get("booking_params"):
            try:
                d["booking_params"] = json.loads(d["booking_params"])
            except Exception:
                d["booking_params"] = None
        rows.append(d)
    return rows[::-1]


# ---------------------------------------------------------------------------
# Notified slots
# ---------------------------------------------------------------------------

def has_notified_slot(user_id: int, venue_id: str, date: str, time: str, party_size: int) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM notified_slots WHERE user_id=? AND venue_id=? AND date=? AND time=? AND party_size=?",
        (user_id, venue_id, date, time, party_size),
    ).fetchone()
    return row is not None


def add_notified_slot(user_id: int, venue_id: str, date: str, time: str, party_size: int) -> None:
    conn = get_connection()
    from datetime import timezone
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO notified_slots (user_id, venue_id, date, time, party_size, notified_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, venue_id, date, time, party_size, now),
        )


def remove_stale_notified_slots(
    user_id: int, venue_id: str, date: str, party_size: int, current_times: set
) -> None:
    conn = get_connection()
    with conn:
        if not current_times:
            conn.execute(
                "DELETE FROM notified_slots WHERE user_id=? AND venue_id=? AND date=? AND party_size=?",
                (user_id, venue_id, date, party_size),
            )
        else:
            placeholders = ",".join("?" * len(current_times))
            conn.execute(
                f"DELETE FROM notified_slots WHERE user_id=? AND venue_id=? AND date=? AND party_size=? AND time NOT IN ({placeholders})",
                [user_id, venue_id, date, party_size, *current_times],
            )


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

def add_booking(booking: Dict[str, Any], user_id: int) -> int:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO bookings (user_id, restaurant_id, venue_id, date, time, party_size, resy_token, status, booked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                booking["restaurant_id"],
                booking["venue_id"],
                booking["date"],
                booking["time"],
                booking["party_size"],
                booking.get("resy_token"),
                booking.get("status", "confirmed"),
                now,
            ),
        )
    return cursor.lastrowid


def get_bookings(user_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT b.id, b.restaurant_id, b.venue_id, b.date, b.time, b.party_size,
               b.resy_token, b.status, b.booked_at, r.name as restaurant_name
        FROM bookings b
        LEFT JOIN restaurants r ON b.restaurant_id = r.id
        WHERE b.user_id = ?
        ORDER BY b.booked_at DESC
        """,
        (user_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def cancel_booking(booking_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Mark a booking cancelled. Returns the booking's state before update, or None if not found."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM bookings WHERE id = ? AND user_id = ?", (booking_id, user_id)
    ).fetchone()
    if not row:
        return None
    booking = dict(row)
    with conn:
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    return booking


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

def get_user_settings(user_id: int) -> Dict[str, str]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {env_key: "" for env_key in _USER_SETTINGS_COLUMNS}
    return {env_key: (row[col] or "") for env_key, col in _USER_SETTINGS_COLUMNS.items()}


def save_user_settings(settings: Dict[str, str], user_id: int) -> None:
    col_updates = {
        col: settings[env_key]
        for env_key, col in _USER_SETTINGS_COLUMNS.items()
        if env_key in settings
    }
    if not col_updates:
        return
    conn = get_connection()
    set_clause = ", ".join(f"{col} = ?" for col in col_updates)
    values = list(col_updates.values()) + [user_id]
    with conn:
        conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
        conn.execute(f"UPDATE user_settings SET {set_clause} WHERE user_id = ?", values)


def seed_user_settings_from_env(user_id: int) -> None:
    """Seed a new user's settings from .env so existing credentials carry over."""
    conn = get_connection()
    if conn.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,)).fetchone():
        return
    conn.execute(
        """
        INSERT INTO user_settings (
            user_id, notify_provider, ntfy_topic,
            pushover_user_key, pushover_app_token, pushover_token, pushover_user,
            smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from, smtp_to,
            enable_email, enable_push,
            resy_api_key, resy_auth_token, auto_book, resy_payment_method_id, check_interval_minutes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            os.getenv("NOTIFY_PROVIDER", "ntfy"),
            os.getenv("NTFY_TOPIC", ""),
            os.getenv("PUSHOVER_USER_KEY", ""),
            os.getenv("PUSHOVER_APP_TOKEN", ""),
            os.getenv("PUSHOVER_TOKEN", ""),
            os.getenv("PUSHOVER_USER", ""),
            os.getenv("SMTP_HOST", ""),
            os.getenv("SMTP_PORT", ""),
            os.getenv("SMTP_USER", ""),
            os.getenv("SMTP_PASS", ""),
            os.getenv("FROM_EMAIL", ""),
            os.getenv("NOTIFY_EMAIL", ""),
            os.getenv("NOTIFY_VIA_EMAIL", "true"),
            os.getenv("NOTIFY_VIA_PUSH", "true"),
            os.getenv("RESY_API_KEY", ""),
            os.getenv("RESY_AUTH_TOKEN", ""),
            os.getenv("AUTO_BOOK", "false"),
            os.getenv("RESY_PAYMENT_METHOD_ID", ""),
            os.getenv("CHECK_INTERVAL_MINUTES", "20"),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Legacy migration (restaurants.py → DB)
# ---------------------------------------------------------------------------

def ensure_migrated(config_restaurants: List[Dict[str, Any]], user_id: int = 1) -> None:
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM restaurants WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    if count > 0:
        return

    if not config_restaurants:
        return

    for restaurant in config_restaurants:
        source = restaurant.get("source", "resy").lower()
        party_sizes = restaurant.get("party_sizes")
        if not party_sizes:
            party_sizes = [restaurant.get("party_size", 2)]
        if isinstance(party_sizes, int):
            party_sizes = [party_sizes]

        days = restaurant.get("days", [])
        time_ranges = {}
        time_range = restaurant.get("time_range")
        if isinstance(time_range, (list, tuple)) and len(time_range) == 2:
            time_ranges = {day: list(time_range) for day in days}

        add_restaurant(
            {
                "name": restaurant.get("name", "Unknown"),
                "source": source,
                "resy_venue_id": restaurant.get("resy_venue_id") if source == "resy" else None,
                "opentable_rid": restaurant.get("opentable_rid") if source == "opentable" else None,
                "party_sizes": party_sizes,
                "days": days,
                "time_ranges": time_ranges,
                "enabled": True,
            },
            user_id=user_id,
        )
    add_activity_log("Migrated restaurant configuration from restaurants.py", "info", user_id=user_id)
