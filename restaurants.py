# Restaurant Reservation Configuration
# Add restaurants you want to monitor here
# Use 'source' to specify 'resy' or 'opentable' (defaults to 'resy')

RESTAURANTS = [
    # Example Resy restaurant
    {
        "name": "Nobu Malibu",
        "source": "resy",
        "resy_venue_id": "1234",  # Replace with actual venue ID
        "party_size": 2,
        "days": ["Friday", "Saturday"],
        "time_range": ("18:00", "22:00"),  # Optional: filter by time window
    },
    # Example OpenTable restaurant
    # {
    #     "name": "The Spotted Pig",
    #     "source": "opentable",
    #     "opentable_rid": "12345",  # OpenTable restaurant ID
    #     "party_size": 4,
    #     "days": ["Friday", "Saturday", "Sunday"],
    #     "time_range": ("19:00", "21:30"),
    # },
]

# Days of the week for filtering
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Check interval in minutes (how often to check for availability)
CHECK_INTERVAL_MINUTES = 20

# Configuration Notes:
# ---------------------
#
# Finding Resy Venue IDs:
# 1. Go to the restaurant's Resy page (e.g., https://resy.com/city/sf/search?venue=restaurant-name)
# 2. Click on the restaurant
# 3. Extract the venue ID from the URL or page source
# 4. Or use browser DevTools > Network tab, search for "api.resy.com" requests
#    and find the venue ID in query parameters
#
# Finding OpenTable Restaurant IDs:
# 1. Go to OpenTable (e.g., https://opentable.com/r/restaurant-name)
# 2. The restaurant ID (rid) is the last number in the URL
# 3. Or use browser DevTools to inspect network requests to "platform.opentable.com"
#
# Time Range Format:
# - Use 24-hour format (HH:MM)
# - Optional but recommended for filtering results
# - Helps avoid slots outside your preferred dining times
#
# Days Configuration:
# - Use full day names (Monday, Tuesday, etc.)
# - List only the days you want to monitor
# - Useful for weekend-only or specific day searches