"""Rule-based recommender: ranks places for the current weather, power status and user location."""
from math import asin, cos, radians, sin, sqrt


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def _reason(text, tone):
    return {"text": text, "tone": tone}


def _score(place, context, prefs):
    """Return (score, reasons, distance_km) for one place."""
    score, reasons = 0.0, []
    weather = context["weather"]

    # --- Weather ---
    if weather["is_wet"]:
        if place.is_indoor:
            score += 5
            reasons.append(_reason("Indoors, so you stay dry", "good"))
        else:
            score -= 3
            reasons.append(_reason("Outdoors, so it may be wet", "warn"))
    elif weather["is_hot"]:
        if place.category == "Beach":
            score += 4
            reasons.append(_reason("Hot day, perfect for the water", "good"))
        elif place.is_indoor:
            score += 2
            reasons.append(_reason("Cool and sheltered from the heat", "good"))
    elif weather["is_cold"]:
        if place.is_indoor:
            score += 2
            reasons.append(_reason("Warm and sheltered", "good"))
    elif not place.is_indoor:
        score += 3
        reasons.append(_reason("Great weather to be outside", "good"))

    # --- Load-shedding ---
    if context["loadshedding"]:
        if place.has_generator:
            score += 5
            reasons.append(_reason("Backup generator during load-shedding", "good"))
        else:
            score -= 5
            reasons.append(_reason("May be affected by load-shedding", "warn"))

    # --- Safety (3.0 is neutral) ---
    safety = place.safety_score if place.safety_score is not None else 3.0
    score += (safety - 3.0) * 2
    min_safety = prefs.get("min_safety")
    if min_safety and safety < min_safety:
        score -= 4
        reasons.append(_reason("Below your safety preference", "warn"))
    elif safety >= 4.5:
        reasons.append(_reason("Highly rated for safety", "good"))

    # --- Distance (only when the user shared a location) ---
    distance = None
    if prefs.get("lat") is not None and prefs.get("lon") is not None:
        distance = haversine_km(prefs["lat"], prefs["lon"], place.latitude, place.longitude)
        score -= min(distance / 25, 6)          # lose up to 6 points for far-away spots
        if distance <= 15:
            reasons.append(_reason(f"Only {distance:.0f} km away", "info"))

    return score, reasons, distance


def recommend_places(places, prefs, context):
    """Rank places (never drops any). Returns a list of dicts, best first."""
    results = []
    for place in places:
        score, reasons, distance = _score(place, context, prefs)
        item = place.to_dict()
        item.update(
            score=round(score, 1),
            reasons=reasons or [_reason("A solid all-round choice", "info")],
            distance_km=None if distance is None else round(distance, 1),
        )
        results.append(item)
    results.sort(key=lambda r: (-r["score"], r["name"]))
    return results
