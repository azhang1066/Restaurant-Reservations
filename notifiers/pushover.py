import logging
import os

import httpx

from .base import BaseNotifier, format_slot_body

logger = logging.getLogger(__name__)


class PushoverNotifier(BaseNotifier):
    def __init__(self, settings: dict = None) -> None:
        self._settings = settings or {}

    def send(self, restaurant_name: str, slot: dict, urls: dict) -> bool:
        user_key = (self._settings.get("PUSHOVER_USER_KEY") or os.getenv("PUSHOVER_USER_KEY", "")).strip()
        app_token = (self._settings.get("PUSHOVER_APP_TOKEN") or os.getenv("PUSHOVER_APP_TOKEN", "")).strip()

        if not user_key or not app_token:
            logger.warning("Pushover credentials not configured (PUSHOVER_USER_KEY / PUSHOVER_APP_TOKEN)")
            return False

        web_url = urls.get("web_url", "")
        body = format_slot_body(slot)

        data = {
            "token": app_token,
            "user": user_key,
            "title": restaurant_name,
            "message": body,
            "priority": 1,
        }
        if web_url:
            data["url"] = web_url
            data["url_title"] = "Book Now"

        try:
            response = httpx.post(
                "https://api.pushover.net/1/messages.json",
                data=data,
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
