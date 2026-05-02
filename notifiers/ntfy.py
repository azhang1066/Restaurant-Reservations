import logging
import os

import httpx

from .base import BaseNotifier, format_slot_body

logger = logging.getLogger(__name__)


class NtfyNotifier(BaseNotifier):
    def send(self, restaurant_name: str, slot: dict, booking_url: str) -> bool:
        topic = os.getenv("NTFY_TOPIC", "").strip()
        if not topic:
            logger.warning("NTFY_TOPIC not configured")
            return False

        body = format_slot_body(slot)

        try:
            response = httpx.post(
                f"https://ntfy.sh/{topic}",
                content=body.encode(),
                headers={
                    "Title": restaurant_name,
                    "Priority": "high",
                    "Click": booking_url,
                    "Tags": "fork_and_knife",
                },
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
