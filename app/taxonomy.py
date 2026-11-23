"""Categories, subcategories and regions used by places. Subcategories are stored as short slugs."""

# Existing categories stay as they are. Nightlife and Stay are newer; Stay (places to sleep) is kept out of the
# "All" ranking because a hotel is not a destination to visit, and has its own region-grouped view.
CATEGORIES = ["Beach", "Nature", "Adventure", "Culture", "Food", "Shopping", "Entertainment", "Nightlife", "Stay"]
STAY = "Stay"

# category -> {slug: display label}
SUBCATEGORIES = {
    "Stay": {
        "hotel": "Hotel",
        "guest_house": "Guest house",
        "hostel": "Hostel",
        "chalet": "Chalet",
        "camp_site": "Camp site",
    },
    "Nightlife": {
        "nightclub": "Nightclub",
        "bar": "Bar",
        "pub": "Pub",
        "live_music": "Live music",
        "lounge": "Lounge",
        "shisa_nyama": "Shisa nyama",
        "brewery_taproom": "Brewery / taproom",
    },
    "Entertainment": {
        "cinema": "Cinema",
        "theatre": "Theatre",
        "casino": "Casino",
        "bowling": "Bowling",
        "ice_skating": "Ice skating",
        "arcade": "Arcade",
        "comedy": "Comedy",
        "mini_golf": "Mini golf",
        "go_karting": "Go-karting",
        "water_park": "Water park",
        "amusement_park": "Amusement park",
        "events_venue": "Stadium / events venue",
        "music_venue": "Music venue",
    },
}

SUBCATEGORY_LABELS = {slug: label for group in SUBCATEGORIES.values() for slug, label in group.items()}

REGIONS = [
    "Durban", "North Coast", "South Coast", "Midlands",
    "Drakensberg", "Zululand", "Pietermaritzburg", "Other KZN",
]


def subcategory_label(slug):
    return SUBCATEGORY_LABELS.get(slug)


def is_valid_subcategory(slug):
    return slug in SUBCATEGORY_LABELS
