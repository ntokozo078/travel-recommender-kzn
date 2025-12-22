# ml_engine/recommender.py
from .weather_rules import get_weather_impact

def recommend_places(all_places, user_prefs, context):
    """
    Ranks places based on match score but DOES NOT remove them.
    """
    scored_places = []
    
    # 1. Define Context Factors
    # If weather contains 'Rain', 'Drizzle', or 'Thunder', we prefer indoors.
    bad_weather = any(x in context['weather'] for x in ['Rain', 'Drizzle', 'Thunder', 'Storm'])
    is_loadshedding = context['loadshedding']

    for place in all_places:
        score = 0
        reasons = []

        # --- RULE 1: Category Match (The most important) ---
        if place.category == user_prefs.get('category'):
            score += 10
            reasons.append(f"Matches your interest in {place.category}")

        # --- RULE 2: Weather Context ---
        if bad_weather:
            if place.is_indoor:
                score += 5
                reasons.append("Great indoor spot for rainy weather")
            else:
                # Instead of removing it, we just lower the score slightly
                score -= 2 
                reasons.append("Outdoor spot (might be rainy)")
        else:
            # Sunny/Clear weather
            if not place.is_indoor:
                score += 3
                reasons.append("Great weather for outdoors")

        # --- RULE 3: Power Context ---
        if is_loadshedding:
            if place.has_generator:
                score += 5
                reasons.append("Has generator during loadshedding")
            else:
                score -= 5
                reasons.append("Might be affected by loadshedding")

        # --- Final Packaging ---
        # We attach the score to the object so we can sort later
        place.recommendation_score = score
        # We join the reasons into a single string for the UI
        place.ai_reason = ", ".join(reasons) if reasons else "General recommendation"
        
        scored_places.append(place)

    # 2. Sort by highest score
    scored_places.sort(key=lambda x: x.recommendation_score, reverse=True)

    return scored_places