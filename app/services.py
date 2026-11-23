"""Live context for the recommender: weather (Open-Meteo, no API key) and power status."""
import time
from datetime import datetime

import requests

from ml_engine import describe_weather

FALLBACK_CODE, FALLBACK_TEMP = 1, 24.0


class ContextEngine:
    def __init__(self, timeout=4, cache_seconds=600):
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache = {}

    def get_current_weather(self, lat, lon):
        """Current weather for a point. Always returns a dict; `source` says if it was live."""
        key = (round(lat, 1), round(lon, 1))
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < self.cache_seconds:
            return cached[1]

        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": lat, "longitude": lon, "current_weather": "true"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            current = resp.json()["current_weather"]
            weather = describe_weather(int(current["weathercode"]), float(current["temperature"]))
            weather["source"] = "live"
            self._cache[key] = (time.time(), weather)
            return weather
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            print(f"[weather] falling back to default: {exc}")
            weather = describe_weather(FALLBACK_CODE, FALLBACK_TEMP)
            weather["source"] = "fallback"
            return weather  # not cached, so we retry on the next request

    def check_loadshedding(self, mode="auto"):
        """Power status. Eskom's API is paid, so `auto` uses a simulated evening schedule.

        mode: "on" / "off" force a state (handy for demos), "auto" uses the simulated schedule.
        """
        if mode == "on":
            return True
        if mode == "off":
            return False
        return 18 <= datetime.now().hour <= 20

    def get_context(self, lat, lon, loadshedding="auto"):
        return {
            "weather": self.get_current_weather(lat, lon),
            "loadshedding": self.check_loadshedding(loadshedding),
            "loadshedding_mode": loadshedding,
            "loadshedding_simulated": True,   # no live Eskom feed is wired up
        }
