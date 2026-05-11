import logging
import os
import threading
import time
from datetime import datetime, timezone

import schedule
from dotenv import load_dotenv

import restaurants as restaurant_config
from app import db
from app.availability import (
    check_opentable_availability,
    check_resy_availability,
    filter_slots_by_time,
    get_date_for_day,
    send_email_notification,
)
from deep_links import build_booking_url
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

logger = logging.getLogger(__name__)

last_check_time: datetime | None = None
_check_lock = threading.Lock()

# Cooldowns keyed by (user_id, venue_id) to isolate per-user auto-book rate limiting.
_auto_book_cooldowns: dict[tuple, float] = {}
_COOLDOWN_SECONDS = 60


def is_check_running() -> bool:
    return _check_lock.locked()


def check_restaurant(restaurant: dict, user_settings: dict) -> None:
    source = restaurant.get("source", "resy").lower()
    party_sizes = restaurant.get("party_sizes") or [2]
    days = restaurant.get("days") or []
    time_ranges = restaurant.get("time_ranges") or {}
    user_id = restaurant.get("user_id", 1)

    venue_id = restaurant.get("opentable_rid") if source == "opentable" else restaurant.get("resy_venue_id")
    if not venue_id:
        msg = f"Missing venue ID for {restaurant.get('name', 'Unknown')}"
        logger.warning(msg)
        db.add_activity_log(msg, "warning", user_id=user_id)
        return

    push_enabled = user_settings.get("NOTIFY_VIA_PUSH", "true").lower() == "true"
    email_enabled = user_settings.get("NOTIFY_VIA_EMAIL", "true").lower() == "true"
    auto_book = user_settings.get("AUTO_BOOK", "false").lower() == "true"
    notifier = get_notifier(user_settings)

    notified_this_run: set = set()
    all_available: set = set()

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
                user_id=user_id,
            )

            if source == "opentable":
                slots = check_opentable_availability(venue_id, party_size, date)
            else:
                slots = check_resy_availability(
                    venue_id, party_size, date,
                    api_key=user_settings.get("RESY_API_KEY"),
                    auth_token=user_settings.get("RESY_AUTH_TOKEN"),
                )

            if time_range:
                slots = filter_slots_by_time(slots, time_range)

            current_times = {slot.time for slot in slots}
            all_available.update((date, t) for t in current_times)
            db.remove_stale_notified_slots(user_id, venue_id, date, party_size, current_times)

            if not slots:
                db.add_activity_log(
                    f"🔍 Check complete · nothing found — {restaurant['name']} {day} (size={party_size})",
                    "debug",
                    user_id=user_id,
                )
                continue

            new_slots = []
            skipped_slots = []
            for slot in slots:
                if db.has_notified_slot(user_id, venue_id, date, slot.time, party_size):
                    skipped_slots.append(slot)
                else:
                    new_slots.append(slot)

            if skipped_slots:
                db.add_activity_log(
                    f"🔁 Slot found · skipped (already notified) — {restaurant['name']} {day}: {len(skipped_slots)} slot(s)",
                    "debug",
                    user_id=user_id,
                )

            actually_notified = []
            for slot in new_slots:
                if (date, slot.time) in notified_this_run:
                    db.add_activity_log(
                        f"🔁 Slot found · skipped (larger party already notified) — {restaurant['name']} {day} {slot.time}",
                        "debug",
                        user_id=user_id,
                    )
                    continue

                notified_this_run.add((date, slot.time))
                db.add_notified_slot(user_id, venue_id, date, slot.time, party_size)

                slot_dict = {"date": date, "time": slot.time, "party_size": party_size}
                urls = build_booking_url(source, restaurant, slot_dict)
                booking_url = urls["web_url"]

                booking_params = None
                if source == "resy" and restaurant.get("id"):
                    booking_params = {
                        "restaurant_id": restaurant["id"],
                        "venue_id": venue_id,
                        "date": date,
                        "time": slot.time,
                        "party_size": party_size,
                        "source": "resy",
                    }

                auto_booked = False
                if auto_book and source == "resy":
                    cooldown_key = (user_id, venue_id)
                    now_ts = time.time()
                    last_attempt = _auto_book_cooldowns.get(cooldown_key, 0)
                    if now_ts - last_attempt < _COOLDOWN_SECONDS:
                        db.add_activity_log(
                            f"⏱ Auto-book skipped (cooldown) — {restaurant['name']} {date} {slot.time}",
                            "debug",
                            user_id=user_id,
                        )
                    else:
                        _auto_book_cooldowns[cooldown_key] = now_ts
                        db.add_activity_log(
                            f"🤖 Auto-book attempt — {restaurant['name']}: {date} {slot.time}, Table for {party_size}",
                            "info",
                            user_id=user_id,
                        )
                        try:
                            client = create_resy_client(
                                api_key=user_settings.get("RESY_API_KEY"),
                                auth_token=user_settings.get("RESY_AUTH_TOKEN"),
                            )
                            details = client.get_booking_details(venue_id, date, slot.time, party_size)
                            payment_method_id = user_settings.get("RESY_PAYMENT_METHOD_ID") or details["payment_method_id"]
                            confirmation = client.book_reservation(details["config_id"], payment_method_id)
                            resy_token = confirmation["resy_token"]
                            db.add_booking({
                                "restaurant_id": restaurant.get("id"),
                                "venue_id": venue_id,
                                "date": date,
                                "time": slot.time,
                                "party_size": party_size,
                                "resy_token": resy_token,
                                "status": "confirmed",
                            }, user_id)
                            auto_booked = True
                            booked_msg = f"✅ Booked! {restaurant['name']}: {date} {slot.time}, Table for {party_size} — Confirmation: {resy_token}"
                            db.add_activity_log(booked_msg, "info", highlight=True, user_id=user_id)
                            notifier.send(
                                restaurant["name"],
                                {**slot_dict, "auto_booked": True, "resy_token": resy_token},
                                urls,
                            )
                        except ResySlotUnavailableError as e:
                            db.add_activity_log(
                                f"⚠️ Auto-book failed (slot gone) — {restaurant['name']}: {e}", "warning", user_id=user_id
                            )
                        except ResyPaymentError as e:
                            db.add_activity_log(
                                f"⚠️ Auto-book failed (payment) — {restaurant['name']}: {e}", "warning", user_id=user_id
                            )
                        except ResyAuthError as e:
                            db.add_activity_log(
                                f"⚠️ Auto-book failed (auth) — {restaurant['name']}: {e}", "warning", user_id=user_id
                            )
                        except ResyTimeoutError as e:
                            db.add_activity_log(
                                f"⚠️ Auto-book failed (timeout) — {restaurant['name']}: {e}", "warning", user_id=user_id
                            )
                        except ResyBookingError as e:
                            db.add_activity_log(
                                f"⚠️ Auto-book failed — {restaurant['name']}: {e}", "warning", user_id=user_id
                            )

                if auto_booked:
                    actually_notified.append(slot)
                    continue

                push_ok = push_enabled and notifier.send(restaurant["name"], slot_dict, urls)

                if push_ok:
                    db.add_activity_log(
                        f"✅ Slot found · notification sent — {restaurant['name']}: {date} {slot.time}, Table for {party_size}",
                        "info",
                        highlight=True,
                        url=booking_url,
                        booking_params=booking_params,
                        user_id=user_id,
                    )
                elif push_enabled:
                    db.add_activity_log(
                        f"❌ Notification failed · push — {restaurant['name']}: {date} {slot.time}",
                        "error",
                        url=booking_url,
                        booking_params=booking_params,
                        user_id=user_id,
                    )
                else:
                    db.add_activity_log(
                        f"✅ Slot found — {restaurant['name']}: {date} {slot.time}, Table for {party_size}",
                        "info",
                        highlight=True,
                        url=booking_url,
                        booking_params=booking_params,
                        user_id=user_id,
                    )
                actually_notified.append(slot)

            if email_enabled and actually_notified:
                restaurant_for_email = {**restaurant, "party_size": party_size}
                if not send_email_notification(restaurant_for_email, actually_notified, user_settings):
                    db.add_activity_log(
                        f"❌ Notification failed · email — {restaurant['name']} ({len(actually_notified)} slot(s))",
                        "error",
                        user_id=user_id,
                    )

    if restaurant.get("id"):
        db.set_last_slot_count(restaurant["id"], len(all_available))


def run_check() -> None:
    global last_check_time
    if not _check_lock.acquire(blocking=False):
        logger.info("Check already in progress — skipping")
        return
    try:
        logger.info("Starting availability check")

        active_user_ids = db.get_active_user_ids()

        if not active_user_ids:
            logger.info("No restaurants configured yet.")
            last_check_time = datetime.now(timezone.utc)
            return

        for user_id in active_user_ids:
            user_settings = db.get_user_settings(user_id)
            restaurants = db.get_restaurants(user_id)
            db.add_activity_log("Starting availability check", "info", user_id=user_id)

            for restaurant in restaurants:
                if not restaurant.get("enabled", True):
                    continue
                try:
                    check_restaurant(restaurant, user_settings)
                except Exception as e:
                    logger.error(f"Error checking {restaurant['name']} (user {user_id}): {e}")
                    db.add_activity_log(
                        f"Error checking {restaurant['name']}: {e}", "error", user_id=user_id
                    )

            db.add_activity_log("Availability check complete", "info", user_id=user_id)

        logger.info("Availability check complete")
        last_check_time = datetime.now(timezone.utc)
    finally:
        _check_lock.release()


def start_scheduler() -> None:
    db.init_db()
    db.ensure_migrated(restaurant_config.RESTAURANTS)
    logger.info("Starting scheduler thread")
    try:
        run_check()
        schedule.every(int(os.getenv("CHECK_INTERVAL_MINUTES", 20))).minutes.do(run_check)
        while True:
            schedule.run_pending()
            time.sleep(1)
    except Exception as e:
        logger.error(f"Scheduler error: {e}")


def start_background_scheduler() -> threading.Thread:
    thread = threading.Thread(target=start_scheduler, daemon=True)
    thread.start()
    return thread
