from abc import ABC, abstractmethod
from datetime import datetime


def format_slot_body(slot: dict) -> str:
    date_str = slot.get("date", "")
    time_str = slot.get("time", "")
    party_size = slot.get("party_size", 2)

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day = dt.strftime("%A")
        month = dt.strftime("%B")
        day_num = str(dt.day)
        formatted_date = f"{day} {month} {day_num}"
    except (ValueError, TypeError):
        formatted_date = date_str

    try:
        t = datetime.strptime(time_str, "%H:%M")
        hour = t.hour % 12 or 12
        minute = t.strftime("%M")
        ampm = "am" if t.hour < 12 else "pm"
        formatted_time = f"{hour}:{minute}{ampm}"
    except (ValueError, TypeError):
        formatted_time = time_str

    guests = "1 guest" if party_size == 1 else f"{party_size} guests"
    return f"{formatted_date} · {formatted_time} · {guests}"


class BaseNotifier(ABC):
    @abstractmethod
    def send(self, restaurant_name: str, slot: dict, booking_url: str) -> bool:
        ...
