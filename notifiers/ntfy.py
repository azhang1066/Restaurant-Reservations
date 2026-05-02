import logging
import os

import httpx

from .base import BaseNotifier, format_slot_body

logger = logging.getLogger(__name__)


class NtfyNotifier(BaseNotifier):
    def send(self, restaurant_name: str, slot: dict, urls: dict) -> bool:
        topic = os.getenv("NTFY_TOPIC", "").strip()
        if not topic:
            logger.warning("NTFY_TOPIC not configured")
            return False

        web_url = urls.get("web_url", "")
        app_url = urls.get("app_url", "")
        body = format_slot_body(slot)

        headers = {
            "Title": restaurant_name,
            "Priority": "high",
            "Tags": "fork_and_knife",
        }

        if web_url:
            headers["Click"] = web_url

        # Add a second action button when the native app URL differs from the web URL
        if app_url and app_url != web_url:
            headers["Actions"] = f"view, Open App, {app_url}"

        try:
            response = httpx.post(
                f"https://ntfy.sh/{topic}",
                content=body.encode(),
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(f"ntfy notification sent for {restaurant_name}")
                return True
            logger.error(f"ntfy returned status {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"ntfy send failed: {e}")
            return False
