# ml_engine/weather_rules.py

def get_weather_impact(weather_condition_str):
    """
    Translates a weather condition string (from OpenWeatherMap)
    into filtering rules for the database.
    
    Returns: dictionary with 'requires_indoor' (bool or None) and a 'message'.
    """
    condition = weather_condition_str.lower()
    
    # Bad Weather List
    wet_conditions = ['rain', 'thunderstorm', 'drizzle', 'snow', 'storm']
    
    # Good/Neutral Weather List
    clear_conditions = ['clear', 'sun', 'clouds', 'few clouds']

    if any(x in condition for x in wet_conditions):
        return {
            'requires_indoor': True,
            'message': f"It is currently {weather_condition_str}. We recommend indoor activities."
        }
    
    elif any(x in condition for x in clear_conditions):
        return {
            'requires_indoor': False, # None means "Don't restrict, show everything"
            # However, for an MVP, we might PREFER outdoor activities if sunny:
            'preference': 'outdoor', 
            'message': "Great weather! Outdoor activities are recommended."
        }
        
    else:
        # Fallback for "Mist", "Haze", etc.
        return {
            'requires_indoor': None,
            'message': f"Weather is {weather_condition_str}."
        }