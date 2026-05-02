import logging
import os
import threading
import time

import schedule
from dotenv import load_dotenv

import restaurants as restaurant_config
from app import db
from deep_links import build_booking_url
from main import (
    check_opentable_availability,
    check_resy_availability,
    filter_slots_by_time,
    get_date_for_day,
    send_email_notification,
)
from notifiers import get_notifier

load_dotenv()

logger = logging.getLogger(__name__)


def check_restaurant(restaurant: dict) -> None:
    source = restaurant.get("source", "resy").lower()
    party_sizes = restaurant.get("party_sizes") or [2]
    days = restaurant.get("days") or []
    time_ranges = restaurant.get("time_ranges") or {}

    venue_id = restaurant.get("opentable_rid") if source == "opentable" else restaurant.get("resy_venue_id")
    if not venue_id:
        msg = f"Missing venue ID for {restaurant.get('name', 'Unknown')}"
        logger.warning(msg)
        db.add_activity_log(msg, "warning")
        return

    push_enabled = os.getenv("NOTIFY_VIA_PUSH", "true").lower() == "true"
    email_enabled = os.getenv("NOTIFY_VIA_EMAIL", "true").lower() == "true"
    notifier = get_notifier()

    for party_size in party_sizes:
        for day in days:
            date = get_date_for_day(day)
            if not date:
                continue

            time_range = time_ranges.get(day)
            if time_range:
                time_range = tuple(time_range)

            logger.info(f"Checking {restaurant['name']} ({source}) for {day} ({date}) size={party_size}")
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

            current_times = {slot.time for slot in slots}
            db.remove_stale_notified_slots(venue_id, date, party_size, current_times)

            if not slots:
                db.add_activity_log(
                    f"🔍 Check complete · nothing found — {restaurant['name']} {day} (size={party_size})",
                    "debug",
                )
                continue

            new_slots = []
            skipped_slots = []
            for slot in slots:
                if db.has_notified_slot(venue_id, date, slot.time, party_size):
                    skipped_slots.append(slot)
                else:
                    new_slots.append(slot)

            if skipped_slots:
                db.add_activity_log(
                    f"🔁 Slot found · skipped (already notified) — {restaurant['name']} {day}: {len(skipped_slots)} slot(s)",
                    "debug",
                )

            for slot in new_slots:
                db.add_notified_slot(venue_id, date, slot.time, party_size)

                slot_dict = {"date": date, "time": slot.time, "party_size": party_size}
                urls = build_booking_url(source, restaurant, slot_dict)
                booking_url = urls["web_url"]

                push_ok = push_enabled and notifier.send(restaurant["name"], slot_dict, urls)

                if push_ok:
                    db.add_activity_log(
                        f"✅ Slot found · notification sent — {restaurant['name']}: {date} {slot.time}, {party_size} guest(s)",
                        "info",
                        highlight=True,
                        url=booking_url,
                    )
                elif push_enabled:
                    db.add_activity_log(
                        f"❌ Notification failed · push — {restaurant['name']}: {date} {slot.time}",
                        "error",
                        url=booking_url,
                    )
                else:
                    db.add_activity_log(
                        f"✅ Slot found — {restaurant['name']}: {date} {slot.time}, {party_size} guest(s)",
                        "info",
                        highlight=True,
                        url=booking_url,
                    )

            if email_enabled and new_slots:
                restaurant_for_email = {**restaurant, "party_size": party_size}
                if not send_email_notification(restaurant_for_email, new_slots):
                    db.add_activity_log(
                        f"❌ Notification failed · email — {restaurant['name']} ({len(new_slots)} slot(s))",
                        "error",
                    )


def run_check() -> None:
    logger.info("Starting availability check")
    db.add_activity_log("Starting availability check", "info")

    restaurants = db.get_restaurants()

    if not restaurants:
        msg = "No restaurants configured yet. Add a restaurant in the dashboard."
        logger.info(msg)
        db.add_activity_log(msg, "info")

    for restaurant in restaurants:
        if not restaurant.get("enabled", True):
            continue
        try:
            check_restaurant(restaurant)
        except Exception as e:
            logger.error(f"Error checking {restaurant['name']}: {e}")
            db.add_activity_log(f"Error checking {restaurant['name']}: {e}", "error")

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
