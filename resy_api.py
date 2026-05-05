#!/usr/bin/env python3
"""
Resy and OpenTable API Client Module
Handles all API interactions with better structure and error handling.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

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
        date: Optional[str] = None,
        party_size: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        """
        Search for restaurant venues.
        
        Args:
            query: Search query (restaurant name/cuisine)
            latitude: Latitude for location search
            longitude: Longitude for location search
            date: Date in YYYY-MM-DD format
            party_size: Number of guests
            limit: Maximum results
            
        Returns:
            List of venue results
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        url = f"{self.BASE_URL}/3/search"
        
        params = {
            "query": query or "",
            "lat": latitude,
            "lng": longitude,
            "per_page": limit,
            "sort": "relevance",
        }
        
        # Struct data for availability search
        struct_data = {
            "availability": {
                "start_date": date,
                "end_date": date,
                "party_size": party_size,
            },
            "query": query or "",
            "location": {"latitude": latitude, "longitude": longitude},
        }
        
        try:
            # Note: Actual implementation may vary based on Resy API version
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
            return self._lookup_by_search(slug, coords[0], coords[1])

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

    def _lookup_by_search(self, slug: str, lat: float, lng: float) -> Optional[str]:
        """Search /3/search and find the result whose url_slug matches exactly."""
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
                    return self._extract_venue_id(venue, slug)
            logger.warning(f"No search result matched url_slug={slug!r}")
        except requests.exceptions.Timeout:
            logger.error(f"Timeout on /3/search for slug={slug!r}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP {e.response.status_code} on /3/search for slug={slug!r}")
        except Exception as e:
            logger.error(f"Error on /3/search for slug={slug!r}: {e}")
        return None

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


class OpenTableAPIClient:
    """Client for OpenTable API interactions."""
    
    BASE_URL = "https://platform.opentable.com/v1"
    
    def get_availability(
        self,
        restaurant_id: str,
        party_size: int,
        date: str,
    ) -> list[TimeSlot]:
        """
        Check availability at a specific OpenTable restaurant.
        
        Args:
            restaurant_id: OpenTable restaurant ID
            party_size: Number of guests
            date: Date in YYYY-MM-DD format
            
        Returns:
            List of available time slots
        """
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
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=30,
            )
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


def create_resy_client(
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> ResyAPIClient:
    """Factory function to create a Resy API client."""
    return ResyAPIClient(api_key, auth_token)


def create_opentable_client() -> OpenTableAPIClient:
    """Factory function to create an OpenTable API client."""
    return OpenTableAPIClient()
