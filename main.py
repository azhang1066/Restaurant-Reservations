#!/usr/bin/env python3
"""
Restaurant Reservation Availability Notifier
Monitors Resy and OpenTable for available reservations and sends notifications.
"""

import argparse
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
import schedule
from dotenv import load_dotenv

import restaurants
from app import db
from resy_api import create_resy_client, create_opentable_client, TimeSlot

# Load environment variables
load_dotenv()

# Configure logging
LOG_FILE = "notifier.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def get_resy_headers() -> dict:
    """Get headers for Resy API requests (maintained for compatibility)."""
    api_key = os.getenv("RESY_API_KEY")
    auth_token = os.getenv("RESY_AUTH_TOKEN")
    
    if not api_key or not auth_token:
        logger.error("RESY_API_KEY and RESY_AUTH_TOKEN must be set")
        sys.exit(1)
    
    return {
        "Authorization": f"ResyAPI api_key={api_key}",
        "Resy-Token": auth_token,
    }


def check_resy_availability(venue_id: str, party_size: int, date: str) -> list[TimeSlot]:
    """
    Check Resy for available reservations.
    
    Args:
        venue_id: Resy venue ID
        party_size: Number of guests
        date: Date in YYYY-MM-DD format
    
    Returns:
        List of available time slots
    """
    client = create_resy_client()
    return client.get_availability(venue_id, party_size, date)


def check_opentable_availability(rid: str, party_size: int, date: str) -> list[TimeSlot]:
    """
    Check OpenTable for available reservations.
    
    Args:
        rid: OpenTable restaurant ID
        party_size: Number of guests
        date: Date in YYYY-MM-DD format
    
    Returns:
        List of available time slots
    """
    client = create_opentable_client()
    return client.get_availability(rid, party_size, date)


def get_date_for_day(day_name: str) -> Optional[str]:
    """Get the next occurrence of a specific day of the week."""
    days_map = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
        "Sunday": 6,
    }
    
    if day_name not in days_map:
        return None
    
    target_day = days_map[day_name]
    today = datetime.now()
    days_ahead = target_day - today.weekday()
    
    if days_ahead <= 0:
        days_ahead += 7
    
    next_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    next_date = next_date + timedelta(days=days_ahead)
    
    return next_date.strftime("%Y-%m-%d")


def filter_slots_by_time(slots: list[TimeSlot], time_range: Optional[tuple]) -> list[TimeSlot]:
    """Filter slots by time range."""
    if not time_range:
        return slots
    
    start_time, end_time = time_range
    filtered = []
    
    for slot in slots:
        try:
            slot_time = slot.time  # TimeSlot already has formatted time
            if start_time <= slot_time <= end_time:
                filtered.append(slot)
        except (ValueError, AttributeError):
            continue
    
    return filtered


def send_email_notification(restaurant: dict, slots: list[TimeSlot]) -> bool:
    """Send email notification about available slots."""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    notify_email = os.getenv("NOTIFY_EMAIL")
    from_email = os.getenv("FROM_EMAIL") or smtp_user
    
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, notify_email]):
        logger.warning("Email configuration incomplete, skipping notification")
        return False
    
    subject = f"Reservation Available: {restaurant['name']}"
    
    body = f"Found available reservations at {restaurant['name']}!\n\n"
    body += f"Party size: {restaurant['party_size']}\n"
    body += f"Days: {', '.join(restaurant.get('days', []))}\n\n"
    body += "Available slots:\n"
    
    for slot in slots:
        body += f"  - {slot.datetime}\n"
    
    # Add booking link based on source
    source = restaurant.get("source", "resy").lower()
    if source == "opentable":
        body += f"\nBook now at: https://opentable.com/r/{restaurant.get('opentable_rid')}"
    else:
        body += f"\nBook now at: https://resy.com/venues/{restaurant.get('resy_venue_id')}"
    
    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = notify_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    
    try:
        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, notify_email, msg.as_string())
        server.quit()
        logger.info(f"Email notification sent for {restaurant['name']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_pushover_notification(restaurant: dict, slots: list[TimeSlot]) -> bool:
    """Send Pushover notification about available slots."""
    token = os.getenv("PUSHOVER_TOKEN")
    user = os.getenv("PUSHOVER_USER")
    
    if not token or not user:
        logger.debug("Pushover not configured, skipping")
        return False
    
    import urllib.request
    import urllib.parse
    
    message = f"Found {len(slots)} available slot(s) at {restaurant['name']}!\n"
    for slot in slots[:5]:  # Limit to first 5 slots
        message += f"  - {slot.datetime}\n"
    if len(slots) > 5:
        message += f"  ... and {len(slots) - 5} more"
    
    data = {
        "token": token,
        "user": user,
        "message": message,
        "title": f"Reservation: {restaurant['name']}",
    }
    
    try:
        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json",
            data=urllib.parse.urlencode(data).encode(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                logger.info(f"Pushover notification sent for {restaurant['name']}")
                return True
            else:
                logger.error(f"Pushover error: {response.status}")
                return False
    except Exception as e:
        logger.error(f"Failed to send Pushover notification: {e}")
        return False


def send_notification(restaurant: dict, slots: list[TimeSlot]) -> None:
    """Send notification via all configured channels."""
    if not slots:
        return
    
    # Try Pushover first (faster)
    pushover_sent = send_pushover_notification(restaurant, slots)
    
    # Always try email as backup
    email_sent = send_email_notification(restaurant, slots)
    
    if not pushover_sent and not email_sent:
        logger.warning(f"No notifications sent for {restaurant['name']}")


def check_restaurant(restaurant: dict) -> list[TimeSlot]:
    """Check a single restaurant for availability."""
    source = restaurant.get("source", "resy").lower()
    party_size = restaurant.get("party_size", 2)
    days = restaurant.get("days", [])
    time_range = restaurant.get("time_range")

    if source == "opentable":
        venue_id = restaurant.get("opentable_rid")
    else:
        venue_id = restaurant.get("resy_venue_id")

    if not venue_id:
        logger.warning(f"Missing venue_id for {restaurant.get('name', 'Unknown')}")
        return []

    all_available_slots = []

    for day in days:
        date = get_date_for_day(day)
        if not date:
            continue

        logger.info(f"Checking {restaurant['name']} ({source}) for {day} ({date})")

        if source == "opentable":
            slots = check_opentable_availability(venue_id, party_size, date)
        else:
            slots = check_resy_availability(venue_id, party_size, date)

        if time_range:
            slots = filter_slots_by_time(slots, time_range)

        current_times = {slot.time for slot in slots}
        db.remove_stale_notified_slots(venue_id, date, party_size, current_times)

        new_slots = []
        for slot in slots:
            if not db.has_notified_slot(venue_id, date, slot.time, party_size):
                new_slots.append(slot)
                db.add_notified_slot(venue_id, date, slot.time, party_size)

        if new_slots:
            logger.info(f"Found {len(new_slots)} new slot(s) at {restaurant['name']} for {day}")
            all_available_slots.extend(new_slots)
        else:
            logger.debug(f"No new slots found at {restaurant['name']} for {day}")

    return all_available_slots


def run_check() -> None:
    """Run a single check for all restaurants."""
    logger.info("=" * 50)
    logger.info("Starting availability check")

    db.init_db()

    for restaurant in restaurants.RESTAURANTS:
        slots = check_restaurant(restaurant)

        if slots:
            send_notification(restaurant, slots)

    logger.info("Availability check complete")
    logger.info("=" * 50)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Restaurant Reservation Availability Notifier"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run a single check immediately without scheduling",
    )
    parser.add_argument(
        "--test-notify",
        action="store_true",
        help="Send a test push notification and exit (no scheduling)",
    )
    args = parser.parse_args()

    logger.info("Restaurant Reservation Notifier started")

    if args.test_notify:
        from notifiers import get_notifier
        notifier = get_notifier()
        provider = os.getenv("NOTIFY_PROVIDER", "ntfy")
        test_slot = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": "19:30",
            "party_size": 2,
        }
        success = notifier.send("Test Restaurant", test_slot, "https://resy.com")
        if success:
            logger.info(f"Test notification sent via {provider}")
        else:
            logger.error(f"Test notification failed via {provider} — check your configuration")
        sys.exit(0)

    if args.test:
        logger.info("Running in test mode (single check)")
        run_check()
    else:
        logger.info(f"Running in scheduled mode (every {restaurants.CHECK_INTERVAL_MINUTES} minutes)")
        
        # Run immediately on start
        run_check()
        
        # Schedule recurring checks
        schedule.every(restaurants.CHECK_INTERVAL_MINUTES).minutes.do(run_check)
        
        while True:
            schedule.run_pending()


if __name__ == "__main__":
    main()