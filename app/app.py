import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from . import db
from .notifier import start_background_scheduler
from lookup_venue import parse_opentable_url, parse_resy_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

scheduler_thread = start_background_scheduler()


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

    restaurant = {
        "name": payload["name"].strip(),
        "source": payload["source"].strip().lower(),
        "resy_venue_id": payload.get("resy_venue_id"),
        "opentable_rid": payload.get("opentable_rid"),
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
        venue_id, venue_name = result
        return jsonify(
            {
                "source": "resy",
                "name": venue_name,
                "resy_venue_id": venue_id,
            }
        )

    result = parse_opentable_url(url)
    if result:
        restaurant_id, restaurant_name = result
        return jsonify(
            {
                "source": "opentable",
                "name": restaurant_name,
                "opentable_rid": restaurant_id,
            }
        )

    return jsonify({"error": "Could not resolve URL. Please provide a Resy or OpenTable URL."}), 400


@app.route("/api/logs", methods=["GET"])
def list_logs():
    return jsonify(db.get_recent_logs())


@app.route("/api/settings", methods=["GET"])
def get_settings():
    env = _load_env()
    keys = [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASS",
        "NOTIFY_EMAIL",
        "FROM_EMAIL",
        "PUSHOVER_TOKEN",
        "PUSHOVER_USER",
        "RESY_API_KEY",
        "RESY_AUTH_TOKEN",
    ]
    return jsonify({key: env.get(key, "") for key in keys})


@app.route("/api/settings", methods=["POST"])
def save_settings():
    payload = request.get_json(force=True)
    settings = {key: payload.get(key, "") for key in _load_env().keys()}
    if not settings:
        settings = payload
    _save_env(settings)
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
