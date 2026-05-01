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
