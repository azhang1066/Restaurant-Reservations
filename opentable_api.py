import logging

import requests

from resy_api import TimeSlot

logger = logging.getLogger(__name__)


class OpenTableAPIClient:
    """Client for OpenTable API interactions."""

    BASE_URL = "https://platform.opentable.com/v1"

    def get_availability(
        self,
        restaurant_id: str,
        party_size: int,
        date: str,
    ) -> list[TimeSlot]:
        url = f"{self.BASE_URL}/restaurants/{restaurant_id}/availability"

        params = {
            "partySize": party_size,
            "startDate": date,
            "endDate": date,
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            slots = []
            for availability in data.get("availabilities", []):
                slot_time = availability.get("time", "")
                if slot_time:
                    slots.append(TimeSlot(
                        date=date,
                        time=slot_time,
                        datetime=f"{date}T{slot_time}:00",
                        venue_id=restaurant_id,
                        source="opentable",
                    ))

            logger.debug(f"Found {len(slots)} slots at OpenTable {restaurant_id} on {date}")
            return slots

        except requests.exceptions.Timeout:
            logger.error(f"Timeout checking OpenTable availability for {restaurant_id}")
            return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"OpenTable restaurant {restaurant_id} not found")
            else:
                logger.error(f"OpenTable HTTP error {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error checking OpenTable availability: {e}")
            return []


def create_opentable_client() -> OpenTableAPIClient:
    return OpenTableAPIClient()
