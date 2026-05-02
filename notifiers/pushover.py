import logging
import os

import httpx

from .base import BaseNotifier, format_slot_body

logger = logging.getLogger(__name__)


class PushoverNotifier(BaseNotifier):
    def send(self, restaurant_name: str, slot: dict, booking_url: str) -> bool:
        user_key = os.getenv("PUSHOVER_USER_KEY", "").strip()
        app_token = os.getenv("PUSHOVER_APP_TOKEN", "").strip()

        if not user_key or not app_token:
            logger.warning("Pushover credentials not configured (PUSHOVER_USER_KEY / PUSHOVER_APP_TOKEN)")
            return False

        body = format_slot_body(slot)

        try:
            response = httpx.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": app_token,
                    "user": user_key,
                    "title": restaurant_name,
                    "message": body,
                    "priority": 1,
                    "url": booking_url,
                    "url_title": "Book now",
                },
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(f"Pushover notification sent for {restaurant_name}")
                return True
            logger.error(f"Pushover returned status {response.status_code}: {response.text}")
            return False
        except Exception as e:
            logger.error(f"Pushover send failed: {e}")
            return False
