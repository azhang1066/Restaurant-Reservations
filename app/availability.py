import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from resy_api import TimeSlot, create_opentable_client, create_resy_client

logger = logging.getLogger(__name__)


def get_date_for_day(day_name: str) -> Optional[str]:
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
    if not time_range:
        return slots
    start_time, end_time = time_range
    filtered = []
    for slot in slots:
        try:
            if start_time <= slot.time <= end_time:
                filtered.append(slot)
        except (ValueError, AttributeError):
            continue
    return filtered


def check_resy_availability(venue_id: str, party_size: int, date: str) -> list[TimeSlot]:
    return create_resy_client().get_availability(venue_id, party_size, date)


def check_opentable_availability(rid: str, party_size: int, date: str) -> list[TimeSlot]:
    return create_opentable_client().get_availability(rid, party_size, date)


def send_email_notification(restaurant: dict, slots: list[TimeSlot]) -> bool:
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
