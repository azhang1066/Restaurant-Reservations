#!/usr/bin/env python3
"""
Venue ID Lookup Utility
Finds Resy and OpenTable venue IDs for restaurants by name and location.
"""

import argparse
import logging
import sys
from urllib.parse import urlparse

from resy_api import create_resy_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_resy_url(url: str) -> tuple[str, str] | None:
    """
    Parse a Resy URL to extract venue ID and name.

    Args:
        url: Resy URL (e.g., https://resy.com/venues/venue-name/12345)

    Returns:
        Tuple of (venue_id, venue_name) or None if parsing fails
    """
    try:
        parsed = urlparse(url)
        if "resy.com" not in parsed.netloc:
            return None

        # Handle different URL formats
        path_parts = parsed.path.strip("/").split("/")

        # Format: /venues/venue-name/venue-id
        if len(path_parts) >= 3 and path_parts[0] == "venues":
            venue_name = path_parts[1]
            venue_id = path_parts[2]

            # Check if venue_id is numeric
            if venue_id.isdigit():
                return venue_id, venue_name.replace("-", " ").title()

        # Format: /venues/venue-id (numeric ID only)
        elif len(path_parts) == 2 and path_parts[0] == "venues" and path_parts[1].isdigit():
            return path_parts[1], "Unknown Venue"

        return None
    except Exception as e:
        logger.warning(f"Failed to parse Resy URL: {e}")
        return None


def parse_opentable_url(url: str) -> tuple[str, str] | None:
    """
    Parse an OpenTable URL to extract restaurant ID and name.

    Args:
        url: OpenTable URL (e.g., https://opentable.com/r/restaurant-name/r12345)

    Returns:
        Tuple of (restaurant_id, restaurant_name) or None if parsing fails
    """
    try:
        parsed = urlparse(url)
        if "opentable.com" not in parsed.netloc:
            return None

        path_parts = parsed.path.strip("/").split("/")

        # Format: /r/restaurant-name/r12345
        if len(path_parts) >= 3 and path_parts[0] == "r":
            restaurant_name = path_parts[1].replace("-", " ").title()

            # Last part should be the ID (r12345)
            last_part = path_parts[-1]
            if last_part.startswith("r") and last_part[1:].isdigit():
                restaurant_id = last_part[1:]  # Remove 'r' prefix
                return restaurant_id, restaurant_name

        return None
    except Exception as e:
        logger.warning(f"Failed to parse OpenTable URL: {e}")
        return None


def search_resy_venues(name: str, city: str, limit: int = 5) -> list[dict]:
    """
    Search for Resy venues by name and city.

    Args:
        name: Restaurant name
        city: City name
        limit: Maximum results to return

    Returns:
        List of venue dictionaries with id, name, location, etc.
    """
    client = create_resy_client()

    # Geocode city to coordinates (simplified - using major cities)
    city_coords = {
        "new york": (40.7128, -74.0060),
        "nyc": (40.7128, -74.0060),
        "manhattan": (40.7589, -73.9851),
        "brooklyn": (40.6782, -73.9442),
        "los angeles": (34.0522, -118.2437),
        "la": (34.0522, -118.2437),
        "san francisco": (37.7749, -122.4194),
        "sf": (37.7749, -122.4194),
        "chicago": (41.8781, -87.6298),
        "miami": (25.7617, -80.1918),
        "boston": (42.3601, -71.0589),
        "seattle": (47.6062, -122.3321),
        "austin": (30.2672, -97.7431),
        "denver": (39.7392, -104.9903),
        "nashville": (36.1627, -86.7816),
        "new orleans": (29.9511, -90.0715),
        "portland": (45.5152, -122.6784),
        "phoenix": (33.4484, -112.0740),
        "las vegas": (36.1699, -115.1398),
        "san diego": (32.7157, -117.1611),
    }

    # Default to NYC if city not found
    lat, lng = city_coords.get(city.lower(), (40.7128, -74.0060))

    try:
        venues = client.search_venues(
            query=name,
            latitude=lat,
            longitude=lng,
            limit=limit,
        )

        # Filter and format results
        results = []
        for venue in venues:
            results.append({
                "id": venue.get("id", ""),
                "name": venue.get("name", ""),
                "location": venue.get("location", {}),
                "cuisines": venue.get("cuisines", []),
                "price_range": venue.get("price_range", ""),
                "rating": venue.get("rating", ""),
            })

        return results

    except Exception as e:
        logger.error(f"Error searching Resy venues: {e}")
        return []


def search_opentable_venues(name: str, city: str, limit: int = 5) -> list[dict]:
    """
    Search for OpenTable restaurants by name and city.

    Note: OpenTable doesn't have a public search API, so this is limited.
    Users should use the URL parsing method instead.

    Args:
        name: Restaurant name
        city: City name
        limit: Maximum results (not used for OpenTable)

    Returns:
        Empty list (OpenTable search not implemented)
    """
    logger.warning("OpenTable venue search not implemented. Please use URL parsing instead.")
    logger.info("Visit opentable.com, search for the restaurant, and use the URL with --opentable-url")
    return []


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Find Resy and OpenTable venue IDs for restaurants",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search by name and city
  python lookup_venue.py "Carbone" "New York" --resy

  # Parse from Resy URL
  python lookup_venue.py --resy-url "https://resy.com/venues/carbone/12345"

  # Parse from OpenTable URL
  python lookup_venue.py --opentable-url "https://opentable.com/r/carbone/r12345"

  # Search both platforms
  python lookup_venue.py "Nobu" "Los Angeles" --both
        """,
    )

    # URL parsing options
    parser.add_argument(
        "--resy-url",
        help="Parse venue ID from Resy URL (e.g., https://resy.com/venues/venue-name/12345)",
    )
    parser.add_argument(
        "--opentable-url",
        help="Parse restaurant ID from OpenTable URL (e.g., https://opentable.com/r/restaurant-name/r12345)",
    )

    # Search options
    parser.add_argument(
        "name",
        nargs="?",
        help="Restaurant name to search for",
    )
    parser.add_argument(
        "city",
        nargs="?",
        help="City name for search location",
    )

    # Platform selection
    parser.add_argument(
        "--resy",
        action="store_true",
        help="Search Resy venues",
    )
    parser.add_argument(
        "--opentable",
        action="store_true",
        help="Search OpenTable restaurants",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Search both Resy and OpenTable",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of results to show (default: 5)",
    )

    args = parser.parse_args()

    # Handle URL parsing first
    if args.resy_url:
        result = parse_resy_url(args.resy_url)
        if result:
            venue_id, venue_name = result
            print("🎯 Resy Venue Found:")
            print(f"   Name: {venue_name}")
            print(f"   Venue ID: {venue_id}")
            print(f"   URL: https://resy.com/venues/{venue_name.lower().replace(' ', '-')}/{venue_id}")
        else:
            print("❌ Could not parse Resy URL. Expected format: https://resy.com/venues/venue-name/12345")
        return

    if args.opentable_url:
        result = parse_opentable_url(args.opentable_url)
        if result:
            restaurant_id, restaurant_name = result
            print("🍽️  OpenTable Restaurant Found:")
            print(f"   Name: {restaurant_name}")
            print(f"   Restaurant ID: {restaurant_id}")
            print(f"   URL: https://opentable.com/r/{restaurant_name.lower().replace(' ', '-')}/r{restaurant_id}")
        else:
            print("❌ Could not parse OpenTable URL. Expected format: https://opentable.com/r/restaurant-name/r12345")
        return

    # Handle search by name/city
    if not args.name or not args.city:
        parser.error("Restaurant name and city are required for search (or use --resy-url/--opentable-url)")

    # Determine which platforms to search
    search_resy = args.resy or args.both
    search_opentable = args.opentable or args.both

    if not search_resy and not search_opentable:
        search_resy = True  # Default to Resy if nothing specified

    print(f"🔍 Searching for '{args.name}' in {args.city}...")
    print()

    # Search Resy
    if search_resy:
        print("🍽️  Searching Resy...")
        resy_results = search_resy_venues(args.name, args.city, args.limit)

        if resy_results:
            print(f"✅ Found {len(resy_results)} Resy venue(s):")
            for i, venue in enumerate(resy_results, 1):
                print(f"   {i}. {venue['name']}")
                print(f"      Venue ID: {venue['id']}")
                if venue.get('location', {}).get('neighborhood'):
                    print(f"      Neighborhood: {venue['location']['neighborhood']}")
                if venue.get('cuisines'):
                    print(f"      Cuisines: {', '.join(venue['cuisines'][:3])}")
                if venue.get('price_range'):
                    print(f"      Price: {venue['price_range']}")
                print(f"      URL: https://resy.com/venues/{venue['name'].lower().replace(' ', '-')}/{venue['id']}")
                print()
        else:
            print("❌ No Resy venues found matching your search.")
        print()

    # Search OpenTable
    if search_opentable:
        print("🍽️  Searching OpenTable...")
        opentable_results = search_opentable_venues(args.name, args.city, args.limit)

        if opentable_results:
            print(f"✅ Found {len(opentable_results)} OpenTable restaurant(s):")
            for i, restaurant in enumerate(opentable_results, 1):
                print(f"   {i}. {restaurant['name']}")
                print(f"      Restaurant ID: {restaurant['id']}")
                print(f"      URL: https://opentable.com/r/{restaurant['name'].lower().replace(' ', '-')}/r{restaurant['id']}")
                print()
        else:
            print("❌ OpenTable search not available. Please use --opentable-url with a direct URL.")
        print()


if __name__ == "__main__":
    main()