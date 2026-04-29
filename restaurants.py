# Restaurant Reservation Configuration
# Add restaurants you want to monitor here
# Use 'source' to specify 'resy' or 'opentable' (defaults to 'resy')

RESTAURANTS = [
    {
        "name": "Nobu Malibu",
        "source": "resy",
        "resy_venue_id": "1234",  # Replace with actual venue ID
        "party_size": 2,
        "days": ["Friday", "Saturday"],
        "time_range": ("18:00", "22:00"),  # Optional: filter by time window
    },
    # OpenTable example:
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

# Check interval in minutes
CHECK_INTERVAL_MINUTES = 20