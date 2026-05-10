import json
import os
import random
import string
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from . import db
from . import notifier as _notifier
from .notifier import start_background_scheduler
from deep_links import build_booking_url
from lookup_venue import parse_opentable_url, parse_resy_url
from notifiers import get_notifier
from resy_api import (
    create_resy_client,
    ResyBookingError,
    ResySlotUnavailableError,
    ResyPaymentError,
    ResyAuthError,
    ResyTimeoutError,
)

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
    fd, tmp = tempfile.mkstemp(dir=ENV_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            for key, value in current.items():
                tmp_file.write(f"{key}={value}\n")
        Path(tmp).replace(ENV_PATH)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/help")
def help_page():
    return render_template("help.html")


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
        # If the URL didn't contain a numeric venue ID (new format), try to
        # look it up via the Resy API so monitoring can be set up immediately.
        if not venue_id and slug and city:
            venue_id = create_resy_client().get_venue_id_from_slug(slug, city) or ""
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
        "AUTO_BOOK",
        "RESY_PAYMENT_METHOD_ID",
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


@app.route("/api/restaurants/<int:restaurant_id>/book", methods=["POST"])
def book_restaurant(restaurant_id: int):
    restaurant = db.get_restaurant(restaurant_id)
    if not restaurant:
        return jsonify({"success": False, "message": "Restaurant not found.", "data": {}}), 404

    if restaurant.get("source") != "resy":
        return jsonify({"success": False, "message": "One-tap booking is only supported for Resy restaurants.", "data": {}}), 400

    venue_id = restaurant.get("resy_venue_id")
    if not venue_id:
        return jsonify({"success": False, "message": "No Resy venue ID configured for this restaurant.", "data": {}}), 400

    payload = request.get_json(force=True)
    date = payload.get("date")
    time_str = payload.get("time")
    party_size = payload.get("party_size")

    if not all([date, time_str, party_size]):
        return jsonify({"success": False, "message": "date, time, and party_size are required.", "data": {}}), 400

    client = create_resy_client()
    try:
        details = client.get_booking_details(venue_id, date, time_str, int(party_size))
        confirmation = client.book_reservation(details["config_id"], details["payment_method_id"])
        resy_token = confirmation["resy_token"]

        booking_id = db.add_booking({
            "restaurant_id": restaurant_id,
            "venue_id": venue_id,
            "date": date,
            "time": time_str,
            "party_size": int(party_size),
            "resy_token": resy_token,
            "status": "confirmed",
        })
        db.add_activity_log(
            f"✅ Booked! {restaurant['name']}: {date} {time_str}, Table for {party_size} — Token: {resy_token}",
            "info",
            highlight=True,
        )
        return jsonify({
            "success": True,
            "message": f"Booked! Confirmation: {resy_token}",
            "data": {
                "booking_id": booking_id,
                "resy_token": resy_token,
                "restaurant": restaurant["name"],
                "date": date,
                "time": time_str,
                "party_size": int(party_size),
            },
        })

    except ResySlotUnavailableError as e:
        db.add_booking({"restaurant_id": restaurant_id, "venue_id": venue_id, "date": date, "time": time_str, "party_size": int(party_size), "status": "failed"})
        db.add_activity_log(f"❌ Booking failed — {restaurant['name']}: {e}", "error")
        return jsonify({"success": False, "message": str(e), "data": {}}), 409
    except ResyPaymentError as e:
        return jsonify({"success": False, "message": str(e), "data": {}}), 402
    except ResyAuthError as e:
        return jsonify({"success": False, "message": str(e), "data": {}}), 401
    except ResyTimeoutError as e:
        return jsonify({"success": False, "message": str(e), "data": {}}), 504
    except ResyBookingError as e:
        db.add_activity_log(f"❌ Booking failed — {restaurant['name']}: {e}", "error")
        return jsonify({"success": False, "message": str(e), "data": {}}), 400


@app.route("/api/bookings", methods=["GET"])
def list_bookings():
    return jsonify({"success": True, "data": db.get_bookings()})


@app.route("/api/bookings/<int:booking_id>", methods=["DELETE"])
def cancel_booking_endpoint(booking_id: int):
    booking = db.cancel_booking(booking_id)
    if not booking:
        return jsonify({"success": False, "message": "Booking not found.", "data": {}}), 404
    if booking.get("status") == "cancelled":
        return jsonify({"success": False, "message": "Booking is already cancelled.", "data": {}}), 409

    resy_token = booking.get("resy_token")
    if resy_token:
        try:
            create_resy_client().cancel_reservation(resy_token)
        except ResyBookingError as e:
            db.add_activity_log(f"⚠️ Resy cancel API failed for token {resy_token}: {e}", "warning")

    restaurant = db.get_restaurant(booking["restaurant_id"])
    name = restaurant["name"] if restaurant else "Unknown"
    db.add_activity_log(
        f"🚫 Booking cancelled — {name}: {booking['date']} {booking['time']}, Table for {booking['party_size']}",
        "info",
    )
    return jsonify({"success": True, "message": "Booking cancelled.", "data": {}})


@app.route("/api/check-now", methods=["POST"])
def check_now():
    if _notifier.is_check_running():
        return jsonify({"success": False, "message": "A check is already in progress."}), 409
    thread = threading.Thread(target=_notifier.run_check, daemon=True)
    thread.start()
    return jsonify({"success": True, "message": "Check started."})


@app.route("/api/status", methods=["GET"])
def get_status():
    last_check = _notifier.last_check_time
    next_check = None
    if last_check:
        next_check = last_check + timedelta(minutes=int(os.getenv("CHECK_INTERVAL_MINUTES", 20)))
    return jsonify({
        "last_check": last_check.isoformat() if last_check else None,
        "next_check": next_check.isoformat() if next_check else None,
        "restaurant_count": len(db.get_restaurants()),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
