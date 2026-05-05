#!/usr/bin/env python3
"""
Deep link builder for Resy and OpenTable booking flows.

Constructs pre-filled booking URLs so a push notification can drop the user
directly into the reservation confirmation screen, not the restaurant homepage.

URL formats:
  Resy:      resy.com/cities/{city}/venues/{slug}?date=YYYY-MM-DD&seats=N
  OpenTable: www.opentable.com/r/{rid}?covers=N&dateTime=YYYY-MM-DDTHH:MM

Native app deep link schemes (resy:// / opentable://) are not publicly
documented by either platform, so app_url == web_url for now.
"""

import argparse
import logging
import re
import sys
import unicodedata

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def _to_slug(name: str) -> str:
    """Convert a restaurant name to a URL-safe slug matching platform conventions."""
    # Normalize unicode to closest ASCII (é→e, ü→u, etc.)
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    # Lowercase, collapse non-alphanumeric runs to single hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def _resy_candidate(venue: dict, slot: dict) -> str:
    city = venue.get("resy_city", "")
    # Prefer the slug stored at add-time (faithful to the original URL) over
    # a slug re-derived from the display name (lossy for special chars/abbrevs).
    slug = venue.get("resy_slug") or _to_slug(venue.get("name", "venue"))
    date = slot.get("date", "")
    party_size = slot.get("party_size", 2)
    if not city or not slug:
        return ""  # Can't build valid URL without city — HEAD check will fall back
    return f"https://resy.com/cities/{city}/venues/{slug}?date={date}&seats={party_size}"


def _resy_fallback(venue: dict) -> str:
    city = venue.get("resy_city", "")
    slug = venue.get("resy_slug") or _to_slug(venue.get("name", "venue"))
    if city and slug:
        return f"https://resy.com/cities/{city}/venues/{slug}"
    if slug:
        return f"https://resy.com/venues/{slug}"
    return "https://resy.com"


def _opentable_candidate(venue: dict, slot: dict) -> str:
    # Prefer stored slug (faithful to URL) over numeric rid for the web URL
    slug = venue.get("opentable_slug") or venue.get("opentable_rid", "")
    date = slot.get("date", "")
    time_str = slot.get("time", "")
    party_size = slot.get("party_size", 2)
    if not slug:
        return ""
    dt = f"{date}T{time_str}" if time_str else date
    return f"https://www.opentable.com/r/{slug}?covers={party_size}&dateTime={dt}"


def _opentable_fallback(venue: dict) -> str:
    slug = venue.get("opentable_slug") or venue.get("opentable_rid", "")
    if slug:
        return f"https://www.opentable.com/r/{slug}"
    return "https://www.opentable.com"


# ---------------------------------------------------------------------------
# HEAD validation
# ---------------------------------------------------------------------------

def _validate_url(url: str, timeout: float = 2.0) -> bool:
    """
    HEAD request to confirm the URL resolves to a non-error response.
    Returns True on HTTP < 400, False on error or timeout.
    Never blocks longer than `timeout` seconds.
    """
    try:
        response = httpx.head(url, follow_redirects=True, timeout=timeout)
        return response.status_code < 400
    except httpx.TimeoutException:
        logger.warning(f"Deep link HEAD timed out ({timeout}s): {url}")
        return False
    except Exception as e:
        logger.warning(f"Deep link HEAD failed: {url} — {e}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_booking_url(platform: str, venue: dict, slot: dict) -> dict:
    """
    Build a pre-filled booking deep link for a single reservation slot.

    Args:
        platform: "resy" or "opentable"
        venue:    restaurant dict from the watchlist (must have name + venue id)
        slot:     dict with keys: date (YYYY-MM-DD), time (HH:MM), party_size (int)

    Returns:
        {
          "web_url":      pre-filled browser URL (best available),
          "app_url":      native app deep link (same as web_url; no public scheme),
          "fallback_url": restaurant homepage as last resort,
        }
    """
    platform = platform.lower().strip()

    if platform == "resy":
        candidate = _resy_candidate(venue, slot)
        fallback = _resy_fallback(venue)
    elif platform == "opentable":
        candidate = _opentable_candidate(venue, slot)
        fallback = _opentable_fallback(venue)
    else:
        logger.error(f"Unknown platform: {platform!r}")
        return {"web_url": "", "app_url": "", "fallback_url": ""}

    if _validate_url(candidate):
        web_url = candidate
    else:
        logger.warning(
            f"Deep link validation failed, using fallback | platform={platform} "
            f"candidate={candidate} fallback={fallback}"
        )
        web_url = fallback

    return {
        "web_url": web_url,
        "app_url": web_url,       # no public native-app scheme for either platform
        "fallback_url": fallback,
    }


# ---------------------------------------------------------------------------
# CLI (python deep_links.py --platform resy --venue-id 1234 ...)
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a booking deep link for a specific slot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deep_links.py --platform resy --venue-id 12345 --venue-name "Carbone" \\
      --date 2026-05-09 --time 20:00 --party-size 2

  python deep_links.py --platform opentable --venue-id 67890 --venue-name "Nobu" \\
      --date 2026-05-09 --time 19:30 --party-size 4 --no-validate
""",
    )
    parser.add_argument("--platform", required=True, choices=["resy", "opentable"])
    parser.add_argument("--venue-id", default="", help="Numeric venue/restaurant ID (Resy: not required for deep link)")
    parser.add_argument("--venue-name", default="restaurant", help="Venue name (used for slug fallback)")
    parser.add_argument("--venue-slug", default="", help="Resy venue slug from URL (e.g. j-bespoke)")
    parser.add_argument("--venue-city", default="", help="Resy city slug from URL (e.g. new-york-ny)")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--time", default="19:00", help="HH:MM (24h)")
    parser.add_argument("--party-size", type=int, default=2)
    parser.add_argument("--no-validate", action="store_true", help="Skip HEAD validation")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    venue: dict
    if args.platform == "resy":
        venue = {
            "name": args.venue_name,
            "resy_venue_id": args.venue_id,
            "resy_slug": args.venue_slug,
            "resy_city": args.venue_city,
        }
    else:
        venue = {"name": args.venue_name, "opentable_rid": args.venue_id}

    slot = {"date": args.date, "time": args.time, "party_size": args.party_size}

    if args.no_validate:
        # Build without HEAD check
        if args.platform == "resy":
            web_url = _resy_candidate(venue, slot)
            fallback = _resy_fallback(venue)
        else:
            web_url = _opentable_candidate(venue, slot)
            fallback = _opentable_fallback(venue)
        result = {"web_url": web_url, "app_url": web_url, "fallback_url": fallback}
    else:
        result = build_booking_url(args.platform, venue, slot)

    print(f"\nPlatform : {args.platform}")
    print(f"Venue    : {args.venue_name} (id={args.venue_id})")
    print(f"Slot     : {args.date}  {args.time}  {args.party_size}p")
    print(f"\nweb_url      : {result['web_url']}")
    print(f"app_url      : {result['app_url']}")
    print(f"fallback_url : {result['fallback_url']}")

    validated = "skipped" if args.no_validate else ("✓" if result["web_url"] != result["fallback_url"] else "✗ (using fallback)")
    print(f"HEAD check   : {validated}\n")


if __name__ == "__main__":
    _cli()
