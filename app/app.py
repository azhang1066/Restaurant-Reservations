import json
import os
import random
import string
import threading
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from . import db
from . import notifier as _notifier
from .notifier import start_background_scheduler
import restaurants as restaurant_config
from deep_links import build_booking_url
from lookup_venue import parse_opentable_url, parse_resy_url
from notifiers import get_notifier

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

scheduler_thread = start_background_scheduler()


def _validate_party_sizes(sizes) -> bool:
    return (
        isinstance(sizes, list)
        and len(sizes) > 0
        and all(isinstance(s, int) and 1 <= s <= 20 for s in sizes)
    )


def _load_env() -> dict:
    env_values = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as env_file:
            for line in env_file:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                env_values[key.strip()] = value.strip()
    return env_values


def _save_env(settings: dict) -> None:
    current = _load_env()
    current.update(settings)
    with open(ENV_PATH, "w", encoding="utf-8") as env_file:
        for key, value in current.items():
            env_file.write(f"{key}={value}\n")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/restaurants", methods=["GET"])
def list_restaurants():
    return jsonify(db.get_restaurants())


@app.route("/api/restaurants", methods=["POST"])
def create_restaurant():
    payload = request.get_json(force=True)
    required = ["name", "source", "party_sizes", "days"]
    if not all(field in payload for field in required):
        return jsonify({"error": "Missing required restaurant fields."}), 400

    if not _validate_party_sizes(payload.get("party_sizes")):
        return jsonify({"error": "party_sizes must be a non-empty list of integers between 1 and 20."}), 400

    restaurant = {
        "name": payload["name"].strip(),
        "source": payload["source"].strip().lower(),
        "resy_venue_id": payload.get("resy_venue_id"),
        "resy_slug": payload.get("resy_slug") or "",
        "resy_city": payload.get("resy_city") or "",
        "opentable_rid": payload.get("opentable_rid"),
        "opentable_slug": payload.get("opentable_slug") or "",
        "party_sizes": payload.get("party_sizes", []),
        "days": payload.get("days", []),
        "time_earliest": payload.get("time_earliest"),
        "time_latest": payload.get("time_latest"),
        "time_ranges": payload.get("time_ranges", {}),
        "enabled": payload.get("enabled", True),
    }

    restaurant_id = db.add_restaurant(restaurant)
    return jsonify({"id": restaurant_id}), 201


@app.route("/api/restaurants/<int:restaurant_id>", methods=["PUT"])
def update_restaurant(restaurant_id: int):
    payload = request.get_json(force=True)
    restaurant = db.get_restaurant(restaurant_id)
    if not restaurant:
        return jsonify({"error": "Restaurant not found."}), 404

    if "party_sizes" in payload and not _validate_party_sizes(payload["party_sizes"]):
        return jsonify({"error": "party_sizes must be a non-empty list of integers between 1 and 20."}), 400

    restaurant.update(
        {
            "name": payload.get("name", restaurant["name"]).strip(),
            "source": payload.get("source", restaurant["source"]).strip().lower(),
            "resy_venue_id": payload.get("resy_venue_id", restaurant.get("resy_venue_id")),
            "opentable_rid": payload.get("opentable_rid", restaurant.get("opentable_rid")),
            "party_sizes": payload.get("party_sizes", restaurant.get("party_sizes", [])),
            "days": payload.get("days", restaurant.get("days", [])),
            "time_earliest": payload.get("time_earliest", restaurant.get("time_earliest")),
            "time_latest": payload.get("time_latest", restaurant.get("time_latest")),
            "time_ranges": payload.get("time_ranges", restaurant.get("time_ranges", {})),
            "enabled": payload.get("enabled", restaurant.get("enabled", True)),
        }
    )
    db.update_restaurant(restaurant_id, restaurant)
    return jsonify({"success": True})


@app.route("/api/restaurants/<int:restaurant_id>", methods=["DELETE"])
def delete_restaurant(restaurant_id: int):
    removed = db.delete_restaurant(restaurant_id)
    if not removed:
        return jsonify({"error": "Restaurant not found."}), 404
    return jsonify({"success": True})


@app.route("/api/restaurants/<int:restaurant_id>/toggle", methods=["POST"])
def toggle_restaurant(restaurant_id: int):
    payload = request.get_json(force=True)
    enabled = bool(payload.get("enabled", True))
    restaurant = db.get_restaurant(restaurant_id)
    if not restaurant:
        return jsonify({"error": "Restaurant not found."}), 404
    restaurant["enabled"] = enabled
    db.update_restaurant(restaurant_id, restaurant)
    return jsonify({"success": True, "enabled": enabled})


@app.route("/api/resolve-url", methods=["POST"])
def resolve_url():
    payload = request.get_json(force=True)
    url = payload.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required."}), 400

    result = parse_resy_url(url)
    if result:
        venue_id, venue_name, slug, city = result
        return jsonify(
            {
                "source": "resy",
                "name": venue_name,
                "resy_venue_id": venue_id,
                "resy_slug": slug,
                "resy_city": city,
            }
        )

    result = parse_opentable_url(url)
    if result:
        restaurant_id, restaurant_name, slug = result
        return jsonify(
            {
                "source": "opentable",
                "name": restaurant_name,
                "opentable_rid": restaurant_id,
                "opentable_slug": slug,
            }
        )

    return jsonify({"error": "Could not resolve URL. Please provide a Resy or OpenTable URL."}), 400


@app.route("/api/logs", methods=["GET"])
def list_logs():
    return jsonify(db.get_recent_logs())


@app.route("/api/settings", methods=["GET"])
def get_settings():
    env = _load_env()

    # Auto-generate a random ntfy topic on first load so the user has one ready
    if not env.get("NTFY_TOPIC"):
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        env["NTFY_TOPIC"] = f"resy-notifier-{suffix}"
        _save_env({"NTFY_TOPIC": env["NTFY_TOPIC"]})

    keys = [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASS",
        "NOTIFY_EMAIL",
        "FROM_EMAIL",
        "PUSHOVER_TOKEN",
        "PUSHOVER_USER",
        "NOTIFY_PROVIDER",
        "NTFY_TOPIC",
        "PUSHOVER_USER_KEY",
        "PUSHOVER_APP_TOKEN",
        "NOTIFY_VIA_EMAIL",
        "NOTIFY_VIA_PUSH",
        "RESY_API_KEY",
        "RESY_AUTH_TOKEN",
    ]
    return jsonify({key: env.get(key, "") for key in keys})


@app.route("/api/settings", methods=["POST"])
def save_settings():
    payload = request.get_json(force=True)
    _save_env(payload)
    return jsonify({"success": True})


@app.route("/api/test-notification", methods=["POST"])
def test_notification():
    notifier = get_notifier()
    provider = os.getenv("NOTIFY_PROVIDER", "ntfy")
    test_slot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": "19:30",
        "party_size": 2,
    }
    # Use a known-good Resy homepage as the test click target
    test_urls = {"web_url": "https://resy.com", "app_url": "https://resy.com", "fallback_url": "https://resy.com"}
    success = notifier.send("Test Restaurant", test_slot, test_urls)
    if success:
        db.add_activity_log(f"Test notification sent via {provider}", "info")
        return jsonify({"success": True, "message": f"Test notification sent via {provider}!"})
    db.add_activity_log(f"Test notification failed via {provider}", "error")
    return jsonify({"success": False, "message": f"Failed — check {provider.upper()} config."}), 400


@app.route("/api/restaurants/<int:restaurant_id>/deep-link", methods=["GET"])
def restaurant_deep_link(restaurant_id: int):
    restaurant = db.get_restaurant(restaurant_id)
    if not restaurant:
        return jsonify({"error": "Restaurant not found."}), 404

    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    time_str = request.args.get("time", "19:00")
    try:
        party_size = int(request.args.get("party_size", restaurant.get("party_sizes", [2])[0]))
    except (ValueError, IndexError):
        party_size = 2

    slot = {"date": date, "time": time_str, "party_size": party_size}
    urls = build_booking_url(restaurant["source"], restaurant, slot)
    return jsonify(urls)


@app.route("/api/check-now", methods=["POST"])
def check_now():
    if _notifier._check_running:
        return jsonify({"success": False, "message": "A check is already in progress."}), 409
    thread = threading.Thread(target=_notifier.run_check, daemon=True)
    thread.start()
    return jsonify({"success": True, "message": "Check started."})


@app.route("/api/status", methods=["GET"])
def get_status():
    last_check = _notifier.last_check_time
    next_check = None
    if last_check:
        next_check = last_check + timedelta(minutes=restaurant_config.CHECK_INTERVAL_MINUTES)
    return jsonify({
        "last_check": last_check.isoformat() if last_check else None,
        "next_check": next_check.isoformat() if next_check else None,
        "restaurant_count": len(db.get_restaurants()),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
