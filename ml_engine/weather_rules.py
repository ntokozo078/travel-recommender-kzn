"""Translate raw weather readings into the flags the recommender cares about."""

# WMO weather interpretation codes used by Open-Meteo.
_WMO = {
    0: ("Clear sky", "sun"),
    1: ("Mostly clear", "sun"),
    2: ("Partly cloudy", "cloud-sun"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Fog", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"),
    57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"),
    81: ("Rain showers", "rain"),
    82: ("Violent showers", "storm"),
    85: ("Snow showers", "snow"),
    86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm with hail", "storm"),
    99: ("Thunderstorm with hail", "storm"),
}
_WET_ICONS = {"rain", "storm", "snow"}
HOT_C = 31
COLD_C = 10


def describe_weather(code, temp_c):
    """Return a dict describing the weather and what it means for outdoor plans."""
    label, icon = _WMO.get(code, ("Clear sky", "sun"))
    wet = icon in _WET_ICONS
    hot = temp_c is not None and temp_c >= HOT_C
    cold = temp_c is not None and temp_c <= COLD_C
    if wet:
        advice = "Wet weather: indoor spots are the safest bet."
    elif hot:
        advice = "Very hot: favour beaches, shade and air-conditioning."
    elif cold:
        advice = "Chilly: dress warm for outdoor plans."
    else:
        advice = "Great weather for getting outside."
    return {
        "code": code,
        "condition": label,
        "icon": icon,
        "temp_c": temp_c,
        "is_wet": wet,
        "is_hot": hot,
        "is_cold": cold,
        "advice": advice,
    }
