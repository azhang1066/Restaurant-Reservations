import logging
import threading
import time
from datetime import datetime

import schedule
from dotenv import load_dotenv

import restaurants as restaurant_config
from app import db
from main import (
    check_opentable_availability,
    check_resy_availability,
    filter_slots_by_time,
    get_date_for_day,
    get_seen_slot_key,
    load_seen_slots,
    save_seen_slots,
    send_notification,
)

# Ensure environment variables are loaded for notifications
load_dotenv()

logger = logging.getLogger(__name__)


def check_restaurant(restaurant: dict, seen_slots: set) -> list:
    source = restaurant.get("source", "resy").lower()
    party_sizes = restaurant.get("party_sizes") or [2]
    days = restaurant.get("days") or []
    time_ranges = restaurant.get("time_ranges") or {}

    if source == "opentable":
        venue_id = restaurant.get("opentable_rid")
    else:
        venue_id = restaurant.get("resy_venue_id")

    if not venue_id:
        message = f"Missing venue ID for {restaurant.get('name', 'Unknown')}"
        logger.warning(message)
        db.add_activity_log(message, "warning")
        return []

    all_available_slots = []

    for party_size in party_sizes:
        for day in days:
            date = get_date_for_day(day)
            if not date:
                continue

            time_range = None
            if time_ranges.get(day):
                time_range = tuple(time_ranges[day])

            logger.info(f"Checking {restaurant['name']} ({source}) for {day} ({date}) party_size={party_size}")
            db.add_activity_log(
                f"Checking {restaurant['name']} ({source}) for {day} ({date}) size={party_size}",
                "debug",
            )

            if source == "opentable":
                slots = check_opentable_availability(venue_id, party_size, date)
            else:
                slots = check_resy_availability(venue_id, party_size, date)

            if time_range:
                slots = filter_slots_by_time(slots, time_range)

            new_slots = []
            for slot in slots:
                slot_key = get_seen_slot_key(venue_id, date, slot.datetime, party_size)
                if slot_key not in seen_slots:
                    new_slots.append(slot)
                    seen_slots.add(slot_key)

            if new_slots:
                logger.info(
                    f"Found {len(new_slots)} new slot(s) at {restaurant['name']} for {day}"
                )
                db.add_activity_log(
                    f"Found {len(new_slots)} new slot(s) at {restaurant['name']} for {day}",
                    "info",
                    highlight=True,
                )
                all_available_slots.extend(new_slots)
            else:
                logger.debug(f"No new slots at {restaurant['name']} for {day}")

    return all_available_slots


def run_check() -> None:
    logger.info("Starting availability check")
    db.add_activity_log("Starting availability check", "info")

    seen_slots = load_seen_slots()
    restaurants = db.get_restaurants()

    if not restaurants:
        message = "No restaurants configured yet. Add a restaurant in the dashboard."
        logger.info(message)
        db.add_activity_log(message, "info")

    for restaurant in restaurants:
        if not restaurant.get("enabled", True):
            continue

        try:
            slots = check_restaurant(restaurant, seen_slots)
            if slots:
                send_notification(restaurant, slots)
                db.add_activity_log(
                    f"Sent notification for {restaurant['name']}", "info", highlight=True
                )
        except Exception as e:
            logger.error(f"Error checking {restaurant['name']}: {e}")
            db.add_activity_log(f"Error checking {restaurant['name']}: {e}", "error")

    save_seen_slots(seen_slots)
    logger.info("Availability check complete")
    db.add_activity_log("Availability check complete", "info")


def start_scheduler() -> None:
    db.init_db()
    db.ensure_migrated(restaurant_config.RESTAURANTS)
    logger.info("Starting scheduler thread")
    try:
        run_check()
        schedule.every(restaurant_config.CHECK_INTERVAL_MINUTES).minutes.do(run_check)
        while True:
            schedule.run_pending()
            time.sleep(1)
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        db.add_activity_log(f"Scheduler error: {e}", "error")


def start_background_scheduler() -> threading.Thread:
    thread = threading.Thread(target=start_scheduler, daemon=True)
    thread.start()
    return thread
