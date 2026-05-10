#!/usr/bin/env python3
"""
Resy API client module — availability checks, venue ID lookup, location_id auto-discovery.
OpenTable client lives in opentable_api.py.
"""

import json as _json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests


class ResyBookingError(Exception):
    """Base class for all Resy booking failures."""


class ResySlotUnavailableError(ResyBookingError):
    """The requested slot is no longer available."""


class ResyPaymentError(ResyBookingError):
    """No valid payment method on file."""


class ResyAuthError(ResyBookingError):
    """Auth token is expired or invalid."""


class ResyTimeoutError(ResyBookingError):
    """Resy API did not respond in time."""

logger = logging.getLogger(__name__)


@dataclass
class TimeSlot:
    """Represents an available reservation time slot."""
    date: str
    time: str
    datetime: str
    venue_id: str
    source: str = "resy"

    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        return {
            "date": self.date,
            "time": self.time,
            "datetime": self.datetime,
            "venue_id": self.venue_id,
            "source": self.source,
        }


class ResyAPIClient:
    """Client for Resy API interactions."""
    
    BASE_URL = "https://api.resy.com"
    
    def __init__(self, api_key: Optional[str] = None, auth_token: Optional[str] = None):
        """
        Initialize Resy API client.
        
        Args:
            api_key: Resy API key (defaults to RESY_API_KEY env var)
            auth_token: Resy auth token (defaults to RESY_AUTH_TOKEN env var)
        """
        self.api_key = api_key or os.getenv("RESY_API_KEY")
        self.auth_token = auth_token or os.getenv("RESY_AUTH_TOKEN")
        
        if not self.api_key or not self.auth_token:
            logger.warning("Resy credentials not configured")
    
    def _get_headers(self) -> dict:
        """Generate proper headers for Resy API requests."""
        return {
            "Authorization": f"ResyAPI api_key={self.api_key}",
            "x-resy-auth-token": self.auth_token,
            "x-resy-universal-auth": self.auth_token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
    
    def search_venues(
        self,
        query: Optional[str] = None,
        latitude: float = 40.7128,
        longitude: float = -74.0060,
        limit: int = 20,
    ) -> list[dict]:
        url = f"{self.BASE_URL}/3/search"
        
        params = {
            "query": query or "",
            "lat": latitude,
            "lng": longitude,
            "per_page": limit,
            "sort": "relevance",
        }

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            
            venues = []
            for result in data.get("results", {}).get("venues", []):
                venues.append({
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "location": result.get("location", {}),
                    "cuisines": result.get("cuisines", []),
                    "price_range": result.get("price_range"),
                    "rating": result.get("rating"),
                    "slots": result.get("slots", []),
                })
            
            logger.info(f"Found {len(venues)} venues matching '{query}'")
            return venues
            
        except requests.exceptions.Timeout:
            logger.error("Resy API request timed out")
            return []
        except requests.exceptions.HTTPError as e:
            logger.error(f"Resy API HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error searching venues: {e}")
            return []
    
    # Resy internal location IDs — confirmed by testing against the /3/venue endpoint.
    # To add a new city: paste a Resy URL and check the numeric ID returned in the
    # API response, then add the city slug → location_id mapping here.
    _LOCATION_IDS: dict[str, int] = {
        "new-york-ny": 1,
    }

    # Approximate centre coordinates for cities not yet in _LOCATION_IDS,
    # used as a fallback search strategy.
    _CITY_COORDS: dict[str, tuple[float, float]] = {
        "los-angeles-ca":    (34.0522, -118.2437),
        "chicago-il":        (41.8781,  -87.6298),
        "miami-fl":          (25.7617,  -80.1918),
        "san-francisco-ca":  (37.7749, -122.4194),
        "washington-dc":     (38.9072,  -77.0369),
        "boston-ma":         (42.3601,  -71.0589),
        "seattle-wa":        (47.6062, -122.3321),
        "austin-tx":         (30.2672,  -97.7431),
        "denver-co":         (39.7392, -104.9903),
        "nashville-tn":      (36.1627,  -86.7816),
        "philadelphia-pa":   (39.9526,  -75.1652),
        "atlanta-ga":        (33.7490,  -84.3880),
        "las-vegas-nv":      (36.1699, -115.1398),
        "portland-or":       (45.5152, -122.6784),
        "new-orleans-la":    (29.9511,  -90.0715),
    }

    def get_venue_id_from_slug(self, slug: str, city: str) -> Optional[str]:
        """
        Look up the numeric Resy venue ID from a URL slug and city slug.

        Primary strategy: GET /3/venue?location_id={id}&url_slug={slug}
            Requires a known location_id for the city (see _LOCATION_IDS).
        Fallback strategy: GET /3/search?query={slug}&lat={lat}&lng={lng}
            Used when the city is not yet in _LOCATION_IDS; matches results
            by url_slug to find the exact venue.

        Args:
            slug: venue URL slug (e.g. "j-bespoke")
            city: city slug from the Resy URL (e.g. "new-york-ny")

        Returns:
            Numeric venue ID as a string, or None if not found / no credentials.
        """
        if not self.api_key or not self.auth_token:
            logger.warning("Resy credentials not configured — cannot look up venue ID")
            return None

        location_id = self._LOCATION_IDS.get(city)
        if location_id:
            return self._lookup_by_location_id(slug, location_id)

        # City not yet mapped — fall back to coordinate-based search.
        coords = self._CITY_COORDS.get(city)
        if coords:
            logger.info(f"No location_id for city={city!r}; using search fallback")
            return self._lookup_by_search(slug, coords[0], coords[1], city)

        logger.warning(
            f"Unknown city {city!r} — add it to _LOCATION_IDS or _CITY_COORDS "
            f"in resy_api.py to enable venue ID lookup"
        )
        return None

    def _lookup_by_location_id(self, slug: str, location_id: int) -> Optional[str]:
        """GET /3/venue?location_id={location_id}&url_slug={slug}"""
        try:
            response = requests.get(
                f"{self.BASE_URL}/3/venue",
                headers=self._get_headers(),
                params={"location_id": location_id, "url_slug": slug},
                timeout=10,
            )
            response.raise_for_status()
            return self._extract_venue_id(response.json(), slug)
        except requests.exceptions.Timeout:
            logger.error(f"Timeout on /3/venue for slug={slug!r}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP {e.response.status_code} on /3/venue for slug={slug!r}")
        except Exception as e:
            logger.error(f"Error on /3/venue for slug={slug!r}: {e}")
        return None

    def _lookup_by_search(self, slug: str, lat: float, lng: float, city: Optional[str] = None) -> Optional[str]:
        """Search /3/search and find the result whose url_slug matches exactly.

        If city is provided and not yet in _LOCATION_IDS, triggers a background
        probe to discover its location_id so future lookups use the faster primary path.
        """
        query = slug.replace("-", " ")
        try:
            response = requests.get(
                f"{self.BASE_URL}/3/search",
                headers=self._get_headers(),
                params={"query": query, "lat": lat, "lng": lng, "per_page": 10},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            for result in data.get("results", {}).get("venues", []):
                venue = result.get("venue") or result
                if venue.get("url_slug") == slug:
                    venue_id = self._extract_venue_id(venue, slug)
                    if venue_id and city and city not in self._LOCATION_IDS:
                        threading.Thread(
                            target=self._auto_discover_location_id,
                            args=(slug, city),
                            daemon=True,
                        ).start()
                    return venue_id
            logger.warning(f"No search result matched url_slug={slug!r}")
        except requests.exceptions.Timeout:
            logger.error(f"Timeout on /3/search for slug={slug!r}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP {e.response.status_code} on /3/search for slug={slug!r}")
        except Exception as e:
            logger.error(f"Error on /3/search for slug={slug!r}: {e}")
        return None

    def _auto_discover_location_id(self, slug: str, city: str) -> Optional[int]:
        """Probe location_ids 1-30 to find the one that owns this slug.

        Updates _LOCATION_IDS in-place on success so future lookups in the same
        process skip the coordinate fallback. Logs a paste-ready hint so the user
        can make the mapping permanent in source.
        """
        for loc_id in range(1, 31):
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/3/venue",
                    headers=self._get_headers(),
                    params={"location_id": loc_id, "url_slug": slug},
                    timeout=5,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                venue = data.get("venue", data)
                if venue.get("url_slug") == slug and self._extract_venue_id(venue, slug):
                    self.__class__._LOCATION_IDS[city] = loc_id
                    logger.info(
                        f"Auto-discovered location_id={loc_id} for city={city!r}. "
                        f"Add '\"{city}\": {loc_id},' to _LOCATION_IDS in resy_api.py to make it permanent."
                    )
                    return loc_id
            except Exception:
                pass
        logger.debug(f"Could not auto-discover location_id for city={city!r} (tried 1-30)")
        return None

    def discover_all_location_ids(self) -> dict[str, int]:
        """Discover location_ids for every city in _CITY_COORDS not already in _LOCATION_IDS.

        For each unmapped city, uses the coordinate search to find any venue, then
        probes location_ids 1-30 to confirm which city bucket it lives in.
        Logs a ready-to-paste _LOCATION_IDS block on completion.

        Requires valid Resy credentials (RESY_API_KEY + RESY_AUTH_TOKEN).
        Run via: python main.py --discover-locations
        """
        result: dict[str, int] = dict(self._LOCATION_IDS)

        for city, (lat, lng) in self._CITY_COORDS.items():
            if city in result:
                logger.info(f"  {city}: {result[city]} (already known)")
                continue

            logger.info(f"  {city}: searching for a sample venue...")
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/3/search",
                    headers=self._get_headers(),
                    params={"query": "", "lat": lat, "lng": lng, "per_page": 5},
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning(f"  {city}: search returned HTTP {resp.status_code}")
                    continue
                venues = resp.json().get("results", {}).get("venues", [])
                slug = next(
                    (
                        (v.get("venue") or v).get("url_slug")
                        for v in venues
                        if (v.get("venue") or v).get("url_slug")
                    ),
                    None,
                )
                if not slug:
                    logger.warning(f"  {city}: no url_slug found in search results")
                    continue

                logger.info(f"  {city}: probing with slug={slug!r}...")
                loc_id = self._auto_discover_location_id(slug, city)
                if loc_id:
                    result[city] = loc_id
                else:
                    logger.warning(f"  {city}: location_id not found in range 1-30")
            except Exception as e:
                logger.error(f"  {city}: error — {e}")

        lines = [f'        "{city}": {lid},' for city, lid in sorted(result.items())]
        logger.info(
            "Discovered _LOCATION_IDS — paste into resy_api.py:\n"
            "    _LOCATION_IDS: dict[str, int] = {\n"
            + "\n".join(lines)
            + "\n    }"
        )
        return result

    @staticmethod
    def _extract_venue_id(data: dict, slug: str) -> Optional[str]:
        """Pull the numeric venue ID out of a /3/venue or search result dict."""
        venue = data.get("venue", data)
        raw_id = venue.get("id")
        if isinstance(raw_id, dict):
            raw_id = raw_id.get("resy")
        if raw_id:
            return str(raw_id)
        logger.warning(f"Venue ID not found in response for slug={slug!r}")
        return None

    def get_availability(
        self,
        venue_id: str,
        party_size: int,
        date: str,
    ) -> list[TimeSlot]:
        """
        Check availability at a specific venue.
        
        Args:
            venue_id: Resy venue ID
            party_size: Number of guests
            date: Date in YYYY-MM-DD format
            
        Returns:
            List of available time slots
        """
        url = f"{self.BASE_URL}/4/venue/{venue_id}/availability"
        
        params = {
            "party_size": party_size,
            "date": date,
        }
        
        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            
            slots = []
            for result in data.get("results", []):
                for slot in result.get("slots", []):
                    slot_date = slot.get("date", {})
                    slot_start = slot_date.get("start", "")
                    
                    if slot_start:
                        # Parse ISO datetime
                        try:
                            dt = datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
                            time_str = dt.strftime("%H:%M")
                        except (ValueError, AttributeError):
                            time_str = ""
                        
                        slots.append(TimeSlot(
                            date=date,
                            time=time_str,
                            datetime=slot_start,
                            venue_id=venue_id,
                            source="resy",
                        ))
            
            logger.debug(f"Found {len(slots)} slots at venue {venue_id} on {date}")
            return slots
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout checking availability for venue {venue_id}")
            return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Venue {venue_id} not found")
            else:
                logger.error(f"HTTP error {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error checking availability: {e}")
            return []


    def get_booking_details(
        self, venue_id: str, date: str, time: str, party_size: int
    ) -> dict:
        """
        GET /3/details — confirm a slot is still open and retrieve the booking config.

        Returns {"config_id": str, "payment_method_id": int|str}.
        Raises ResySlotUnavailableError, ResyPaymentError, ResyAuthError, ResyTimeoutError.
        """
        start = f"{date} {time}:00"
        try:
            response = requests.get(
                f"{self.BASE_URL}/3/details",
                headers=self._get_headers(),
                params={
                    "venue_id": venue_id,
                    "day": date,
                    "party_size": party_size,
                    "type": "Dining",
                    "start": start,
                },
                timeout=15,
            )
        except requests.exceptions.Timeout:
            raise ResyTimeoutError(
                "Resy didn't respond in time — will retry on the next check cycle"
            )

        if response.status_code == 401:
            raise ResyAuthError(
                "Your Resy session has expired — update RESY_API_KEY in Settings"
            )
        if response.status_code == 404:
            raise ResySlotUnavailableError(
                "That slot was just taken — keeping watch for the next one"
            )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            try:
                err = response.json()
                msg = err.get("message") or err.get("error") or f"HTTP {response.status_code}"
            except Exception:
                msg = f"HTTP {response.status_code}"
            raise ResyBookingError(msg)

        data = response.json()

        book_token = data.get("book_token", {})
        config_id = book_token.get("value") if isinstance(book_token, dict) else book_token
        if not config_id:
            raise ResySlotUnavailableError(
                "That slot was just taken — keeping watch for the next one"
            )

        payment = data.get("payment", {})
        payment_method_id = payment.get("id") if isinstance(payment, dict) else None

        env_override = os.getenv("RESY_PAYMENT_METHOD_ID")
        if env_override:
            try:
                payment_method_id = int(env_override)
            except ValueError:
                payment_method_id = env_override

        if payment_method_id is None:
            raise ResyPaymentError(
                "Add a credit card to your Resy account before enabling auto-book"
            )

        return {"config_id": config_id, "payment_method_id": payment_method_id}

    def book_reservation(self, config_id: str, payment_method_id) -> dict:
        """
        POST /3/book — complete the reservation using the config from get_booking_details.

        Returns {"resy_token": str, "reservation_id": any, "confirmation_message": str}.
        Raises ResySlotUnavailableError, ResyAuthError, ResyTimeoutError, ResyBookingError.
        """
        struct_payment = _json.dumps({"id": payment_method_id, "type": "stored"})
        try:
            response = requests.post(
                f"{self.BASE_URL}/3/book",
                headers=self._get_headers(),
                data={
                    "book_token": config_id,
                    "struct_payment_method": struct_payment,
                    "source_id": "resy.com-venue-details",
                },
                timeout=15,
            )
        except requests.exceptions.Timeout:
            raise ResyTimeoutError(
                "Resy didn't respond in time — will retry on the next check cycle"
            )

        if response.status_code == 401:
            raise ResyAuthError(
                "Your Resy session has expired — update RESY_API_KEY in Settings"
            )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            try:
                err = response.json()
                msg = err.get("message") or err.get("error") or f"HTTP {response.status_code}"
            except Exception:
                msg = f"HTTP {response.status_code}"
            if any(x in msg.lower() for x in ("no longer available", "unavailable", "not available")):
                raise ResySlotUnavailableError(
                    "That slot was just taken — keeping watch for the next one"
                )
            raise ResyBookingError(msg)

        data = response.json()
        resy_token = data.get("resy_token") or data.get("reservation_id")
        if not resy_token:
            raise ResyBookingError("Booking succeeded but no confirmation token received")

        return {
            "resy_token": str(resy_token),
            "reservation_id": data.get("reservation_id"),
            "confirmation_message": f"Booked! Confirmation: {resy_token}",
        }

    def cancel_reservation(self, resy_token: str) -> bool:
        """
        DELETE /3/reservation — cancel a previously booked reservation.

        Returns True on success.
        Raises ResyAuthError, ResyTimeoutError, ResyBookingError on failure.
        """
        try:
            response = requests.delete(
                f"{self.BASE_URL}/3/reservation",
                headers=self._get_headers(),
                data={"resy_token": resy_token},
                timeout=15,
            )
            response.raise_for_status()
            return True
        except requests.exceptions.Timeout:
            raise ResyTimeoutError(
                "Resy didn't respond in time — will retry on the next check cycle"
            )
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ResyAuthError(
                    "Your Resy session has expired — update RESY_API_KEY in Settings"
                )
            try:
                err = e.response.json()
                msg = err.get("message") or err.get("error") or f"HTTP {e.response.status_code}"
            except Exception:
                msg = f"HTTP {e.response.status_code}"
            raise ResyBookingError(msg)
        except Exception as e:
            raise ResyBookingError(str(e))


def create_resy_client(
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> ResyAPIClient:
    return ResyAPIClient(api_key, auth_token)
