import json
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
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    target = len(_MIGRATIONS)
    if version >= target:
        return
    # Fresh database: CREATE TABLE IF NOT EXISTS already includes every column,
    # so stamp to the latest version without running ALTER TABLE statements.
    if version == 0:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(restaurants)").fetchall()}
        if "resy_slug" in existing:
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
            CREATE TABLE IF NOT EXISTS restaurants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                highlight INTEGER NOT NULL DEFAULT 0,
                url TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notified_slots (
                venue_id TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                party_size INTEGER NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY (venue_id, date, time, party_size)
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
    }


def get_restaurants() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.execute("SELECT * FROM restaurants ORDER BY id DESC")
    return [_row_to_restaurant(row) for row in cursor.fetchall()]


def get_restaurant(restaurant_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM restaurants WHERE id = ?", (restaurant_id,)).fetchone()
    return _row_to_restaurant(row) if row else None


def add_restaurant(restaurant: Dict[str, Any]) -> int:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO restaurants (
                name, source, resy_venue_id, resy_slug, resy_city,
                opentable_rid, opentable_slug,
                party_sizes, days, time_ranges,
                enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                now,
            ),
        )
    return cursor.lastrowid


def update_restaurant(restaurant_id: int, restaurant: Dict[str, Any]) -> bool:
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
            WHERE id = ?
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
            ),
        )
    return cursor.rowcount > 0


def delete_restaurant(restaurant_id: int) -> bool:
    conn = get_connection()
    with conn:
        cursor = conn.execute("DELETE FROM restaurants WHERE id = ?", (restaurant_id,))
    return cursor.rowcount > 0


def add_activity_log(
    message: str,
    level: str = "info",
    highlight: bool = False,
    url: Optional[str] = None,
) -> None:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    with conn:
        conn.execute(
            "INSERT INTO activity_log (timestamp, level, message, highlight, url) VALUES (?, ?, ?, ?, ?)",
            (now, level, message, int(highlight), url),
        )
        conn.execute(
            "DELETE FROM activity_log WHERE id NOT IN (SELECT id FROM activity_log ORDER BY id DESC LIMIT 500)"
        )


def get_recent_logs(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.execute(
        "SELECT timestamp, level, message, highlight, url FROM activity_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()][::-1]


def ensure_migrated(config_restaurants: List[Dict[str, Any]]) -> None:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0]
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
            }
        )
    add_activity_log("Migrated restaurant configuration from restaurants.py", "info")


def has_notified_slot(venue_id: str, date: str, time: str, party_size: int) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM notified_slots WHERE venue_id=? AND date=? AND time=? AND party_size=?",
        (venue_id, date, time, party_size),
    ).fetchone()
    return row is not None


def add_notified_slot(venue_id: str, date: str, time: str, party_size: int) -> None:
    conn = get_connection()
    from datetime import timezone
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO notified_slots (venue_id, date, time, party_size, notified_at) VALUES (?, ?, ?, ?, ?)",
            (venue_id, date, time, party_size, now),
        )


def remove_stale_notified_slots(
    venue_id: str, date: str, party_size: int, current_times: set
) -> None:
    conn = get_connection()
    rows = conn.execute(
        "SELECT time FROM notified_slots WHERE venue_id=? AND date=? AND party_size=?",
        (venue_id, date, party_size),
    ).fetchall()
    with conn:
        for row in rows:
            if row["time"] not in current_times:
                conn.execute(
                    "DELETE FROM notified_slots WHERE venue_id=? AND date=? AND time=? AND party_size=?",
                    (venue_id, date, row["time"], party_size),
                )
