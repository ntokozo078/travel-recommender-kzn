"""Rule-based, explainable recommender.

Every point added to or taken from a place comes with a reason chip that carries those points, so the
score is always exactly the sum of what the user can see: score == sum(reason["points"]).
Unknown facts (NULL safety, hours, price) never add or remove points.
"""
from math import asin, ceil, cos, radians, sin, sqrt

from etl_pipeline import osm_mapping as om

VIBES = ("nightlife", "family", "nature", "culture", "food", "budget")
BIG_WAVES_M = 2.5                                # forecast waves at or above this are flagged on beaches
EVENING_SAFETY_WEIGHT = 1.5                      # a rated place's safety rating counts 1.5x after dark

DAYLIGHT_CATEGORIES = {"Beach", "Nature", "Adventure"}
EVENING_SUBCATEGORIES = {"cinema", "theatre", "casino", "comedy", "music_venue", "events_venue"}
FAMILY_SUBCATEGORIES = {"cinema", "bowling", "ice_skating", "arcade", "mini_golf", "go_karting",
                        "water_park", "amusement_park", "theatre"}
ADULT_LEANING_SUBCATEGORIES = {"casino"}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def _reason(text, tone, points=0.0):
    return {"text": text, "tone": tone, "points": round(points, 1)}


def _hours(place):
    """(text, open_evening) from the listed hours; flags fall back to parsing the text."""
    text = getattr(place, "opening_hours_raw", None) or getattr(place, "opening_hours", None)
    evening = getattr(place, "open_evening", None)
    if evening is None and text:
        evening = om.parse_opening_hours(text)[0]
    return text, evening


def is_open_now(place, when):
    """True / False from the listed hours at the context time, or None when unknown (never a guess)."""
    text, _ = _hours(place)
    return om.is_open_at(text, when["weekday"], when["minutes"])


def open_late_flag(place):
    """True if listed hours run past 23:00 on some day, False if they provably don't, None if unknown."""
    flag = getattr(place, "open_late", None)
    if flag is None:
        text, _ = _hours(place)
        flag = om.parse_opening_hours(text)[1] if text else None
    return flag


def _weather_and_power(place, context, evening, reasons, weather_rules=True):
    weather = context["weather"]
    if not weather_rules:
        pass                                         # rain, heat and sunshine say nothing about where to sleep
    elif weather["is_wet"]:
        if place.is_indoor:
            reasons.append(_reason("Indoors, so you stay dry", "good", 5))
        else:
            reasons.append(_reason("Outdoors, so it may be wet", "warn", -3))
    elif weather["is_hot"] and not evening:
        if place.category == "Beach":
            reasons.append(_reason("Hot day, perfect for the water", "good", 4))
        elif place.is_indoor:
            reasons.append(_reason("Cool and sheltered from the heat", "good", 2))
    elif weather["is_cold"]:
        if place.is_indoor:
            reasons.append(_reason("Warm and sheltered", "good", 2))
    elif not evening and not place.is_indoor:
        reasons.append(_reason("Great weather to be outside", "good", 3))

    if context.get("loadshedding"):
        if place.has_generator:
            reasons.append(_reason("Backup generator during load-shedding (simulated)", "good", 5))
        else:
            reasons.append(_reason("May be affected by load-shedding (simulated)", "warn", -5))


def _time_of_day(place, context, reasons):
    """Evening vs day, and what the listed opening hours say."""
    when = context.get("time")
    if not when:
        return
    evening = bool(when["evening"])
    text, open_evening = _hours(place)
    subcategory = getattr(place, "subcategory", None)
    state = om.is_open_at(text, when["weekday"], when["minutes"])

    if evening:
        if place.category == "Nightlife":
            reasons.append(_reason("Nightlife is at its best after dark", "good", 6))
        elif place.category == "Entertainment":
            if open_evening is True:
                reasons.append(_reason("Open in the evening (per listed hours)", "good", 4))
            elif open_evening is None and subcategory in EVENING_SUBCATEGORIES:
                reasons.append(_reason("Usually an evening venue (hours not listed)", "info", 2))
        elif place.category in DAYLIGHT_CATEGORIES:
            reasons.append(_reason("Best in daylight", "warn", -4))
    elif place.category == "Nightlife" and state is not True:
        reasons.append(_reason("More of an evening venue", "info", -4))

    if state is False:
        reasons.append(_reason("Closed right now (per listed hours)", "warn", -6))
    elif state is True:
        reasons.append(_reason("Open now (per listed hours)", "good", 2))
    elif evening and open_evening is False:
        reasons.append(_reason("Listed hours end before the evening", "warn", -5))


def _safety(place, prefs, evening, reasons):
    """Curator rating (0-5). NULL = not rated: no points, no chip, never 'unsafe'."""
    rating = place.safety_score
    if rating is None:
        return
    weight = EVENING_SAFETY_WEIGHT if evening else 1.0
    points = (rating - 3.0) * 2 * weight
    if round(points, 1):
        note = " (counts for more in the evening)" if evening else ""
        reasons.append(_reason(f"Curator safety rating {rating:g}/5{note}", "info", points))
    min_safety = prefs.get("min_safety")
    if min_safety and rating < min_safety:
        reasons.append(_reason(f"Curator safety rating {rating:g}/5 is below your minimum", "warn", -4))


def _marine(place, prefs, reasons):
    """Forecast wave height for a beach (when the sea forecast is available). Big waves cost points."""
    data = (prefs.get("marine") or {}).get(getattr(place, "id", None)) if place.category == "Beach" else None
    if not data:
        return
    height = data["wave_height_m"]
    if height >= BIG_WAVES_M:
        reasons.append(_reason(f"Big waves forecast (up to {height:.1f} m)", "warn", -3))
    else:
        reasons.append(_reason(f"Waves up to {height:.1f} m forecast", "info", 0))


def _distance(place, prefs, reasons):
    if prefs.get("lat") is None or prefs.get("lon") is None:
        return None
    km = haversine_km(prefs["lat"], prefs["lon"], place.latitude, place.longitude)
    penalty = min(km / 25, 6)                        # up to 6 points for far-away spots
    reasons.append(_reason(f"{km:.0f} km from you", "warn" if penalty >= 2 else "info", -penalty))
    return km


def _vibes(place, vibes, reasons):
    category = place.category
    sub = getattr(place, "subcategory", None)
    price = getattr(place, "price_tier", None)
    min_age = getattr(place, "min_age", None)
    for vibe in vibes:
        if vibe == "nightlife":
            if category == "Nightlife":
                reasons.append(_reason("Matches your nightlife vibe", "good", 6))
            elif category == "Entertainment" and sub in EVENING_SUBCATEGORIES:
                reasons.append(_reason("An evening out, in line with your nightlife vibe", "good", 3))
        elif vibe == "family":
            if category == "Entertainment" and sub in FAMILY_SUBCATEGORIES:
                reasons.append(_reason("Activity suited to a family outing", "good", 5))
            elif category in ("Nature", "Beach"):
                reasons.append(_reason("Outdoor day out for the family", "good", 3))
            if (category == "Nightlife" or sub in ADULT_LEANING_SUBCATEGORIES) and not (min_age is not None and min_age < 18):
                reasons.append(_reason("Often 18+, so check age rules", "warn", -6))
        elif vibe == "nature":
            if category == "Nature":
                reasons.append(_reason("Matches your nature vibe", "good", 6))
            elif category in ("Beach", "Adventure"):
                reasons.append(_reason("Outdoors, in line with your nature vibe", "good", 3))
        elif vibe == "culture":
            if category == "Culture":
                reasons.append(_reason("Matches your culture vibe", "good", 6))
            elif sub == "theatre":
                reasons.append(_reason("Performing arts, in line with your culture vibe", "good", 2))
        elif vibe == "food":
            if category == "Food":
                reasons.append(_reason("Matches your food vibe", "good", 6))
            elif sub == "brewery_taproom":
                reasons.append(_reason("A taproom, in line with your food-and-drink vibe", "info", 2))
        elif vibe == "budget":
            if price == "$":
                reasons.append(_reason("Budget-friendly ($)", "good", 5))
            elif price == "$$":
                reasons.append(_reason("Mid-range price ($$)", "info", 2))
            elif price == "$$$":
                reasons.append(_reason("Higher price ($$$)", "warn", -3))


def score_place(place, context, prefs):
    """Return (score, reasons, distance_km). score is exactly the sum of the reason points."""
    reasons = []
    when = context.get("time")
    evening = bool(when and when["evening"])
    sleeping = place.category == "Stay"              # lodging: only power, safety, distance and budget matter
    _weather_and_power(place, context, evening, reasons, weather_rules=not sleeping)
    if not sleeping:
        _time_of_day(place, context, reasons)
    _safety(place, prefs, evening, reasons)
    _marine(place, prefs, reasons)
    distance = _distance(place, prefs, reasons)
    _vibes(place, prefs.get("vibes") or (), reasons)
    score = round(sum(r["points"] for r in reasons), 1)
    return score, reasons, distance


def recommend_places(places, prefs, context):
    """Rank places (never drops any). Returns a list of dicts, best first."""
    results = []
    for place in places:
        score, reasons, distance = score_place(place, context, prefs)
        item = place.to_dict()
        item.update(
            score=score,
            reasons=reasons or ([] if place.category == "Stay" else [_reason("A solid all-round choice", "info")]),
            distance_km=None if distance is None else round(distance, 1),
        )
        sea = (prefs.get("marine") or {}).get(getattr(place, "id", None)) if place.category == "Beach" else None
        if sea:
            item["marine"] = sea
        results.append(item)
    results.sort(key=lambda r: (-r["score"], r["name"]))
    return results


def category_cap(limit):
    """How many of the top `limit` may share a category in tourist mode (3 of 12, 1 of 3)."""
    return max(1, ceil(limit / 4))


def diversify(ranked, limit, cap=None):
    """Top `limit` of an already ranked list with at most `cap` per category.

    Best-first order is kept. If there are too few categories to fill the list, the best leftovers
    are appended so the caller still gets `limit` results."""
    cap = cap or category_cap(limit)
    picked, leftovers, used = [], [], {}
    for item in ranked:
        key = item.get("category")
        if used.get(key, 0) < cap and len(picked) < limit:
            picked.append(item)
            used[key] = used.get(key, 0) + 1
        else:
            leftovers.append(item)
    picked.extend(leftovers[: max(0, limit - len(picked))])
    return picked
