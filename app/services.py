"""Live context for the recommender: weather, 7-day forecast and sea conditions (Open-Meteo, no API key)
plus power status. Every outside call has a timeout, is cached, and falls back instead of failing."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from ml_engine import describe_weather

FALLBACK_CODE, FALLBACK_TEMP = 1, 24.0
FORECAST_DAYS = 7
MARINE_TTL = 3600           # sea forecasts change slowly: cache an hour
MARINE_COOLDOWN = 300       # after a failed marine call, don't try again for five minutes
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# Render (and most servers) run on UTC. All "time of day" logic uses South African time (UTC+2, no DST).
SAST = ZoneInfo("Africa/Johannesburg")

# "Evening" for recommendations runs from 17:30 until 04:00 the next morning.
EVENING_START = 17 * 60 + 30
NIGHT_END = 4 * 60


def now_sast():
    return datetime.now(SAST)


def _number(value):
    """float(value), or None for missing / non-numeric values (Open-Meteo uses null)."""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def parse_forecast(daily):
    """Open-Meteo `daily` block -> list of day dicts shaped like the current-weather dict.

    Days with no weather code or no temperature are dropped rather than guessed."""
    times = daily.get("time") or []
    codes = daily.get("weather_code") or daily.get("weathercode") or []
    highs, lows = daily.get("temperature_2m_max") or [], daily.get("temperature_2m_min") or []
    chance, rain = daily.get("precipitation_probability_max") or [], daily.get("precipitation_sum") or []
    days = []
    for i, date in enumerate(times):
        code = _number(codes[i]) if i < len(codes) else None
        high = _number(highs[i]) if i < len(highs) else None
        if code is None or high is None:
            continue
        day = describe_weather(int(code), high)                 # temp_c is the day's high
        low = _number(lows[i]) if i < len(lows) else None
        prob = _number(chance[i]) if i < len(chance) else None
        mm = _number(rain[i]) if i < len(rain) else None
        day.update(
            date=str(date), temp_min_c=low, source="forecast",
            rain_chance_pct=None if prob is None else int(prob),
            rain_mm=mm,
        )
        days.append(day)
    return days


def parse_marine(daily):
    """Open-Meteo marine `daily` block -> {date: {"wave_height_m", "wave_period_s"}}. Inland points are all null."""
    out = {}
    heights, periods = daily.get("wave_height_max") or [], daily.get("wave_period_max") or []
    for i, date in enumerate(daily.get("time") or []):
        height = _number(heights[i]) if i < len(heights) else None
        if height is None:
            continue
        out[str(date)] = {"wave_height_m": round(height, 1),
                          "wave_period_s": _number(periods[i]) if i < len(periods) else None}
    return out


class ContextEngine:
    def __init__(self, timeout=4, cache_seconds=600, clock=None):
        self.clock = clock or now_sast          # injectable so tests can fix the time
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache = {}
        self._forecast_cache = {}
        self._marine_cache = {}
        self._marine_down_until = 0.0

    # ---- weather now ----------------------------------------------------------------
    def get_current_weather(self, lat, lon):
        """Current weather for a point. Always returns a dict; `source` says if it was live."""
        key = (round(lat, 1), round(lon, 1))
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < self.cache_seconds:
            return cached[1]

        try:
            resp = requests.get(
                FORECAST_URL,
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

    # ---- 7-day forecast ---------------------------------------------------------------
    def get_forecast(self, lat, lon):
        """{"days": [...], "source": "live" | "fallback"}. On failure the day list is empty (never made up)."""
        key = (round(lat, 1), round(lon, 1))
        cached = self._forecast_cache.get(key)
        if cached and time.time() - cached[0] < self.cache_seconds:
            return cached[1]
        try:
            resp = requests.get(
                FORECAST_URL,
                params={
                    "latitude": lat, "longitude": lon, "timezone": "Africa/Johannesburg", "forecast_days": FORECAST_DAYS,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            days = parse_forecast(resp.json()["daily"])
            if not days:
                raise ValueError("no usable forecast days")
            result = {"days": days, "source": "live"}
            self._forecast_cache[key] = (time.time(), result)
            return result
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            print(f"[forecast] unavailable: {exc}")
            return {"days": [], "source": "fallback"}          # not cached: retry next time

    def weather_for_date(self, lat, lon, iso_date):
        """The forecast for one day, in the same shape as current weather; the default estimate if unavailable."""
        for day in self.get_forecast(lat, lon)["days"]:
            if day["date"] == iso_date:
                return day
        weather = describe_weather(FALLBACK_CODE, FALLBACK_TEMP)
        weather.update(source="fallback", date=iso_date)
        return weather

    # ---- sea conditions for coastal places ------------------------------------------------
    @staticmethod
    def _cell(lat, lon):
        return round(lat * 2) / 2, round(lon * 2) / 2          # half-degree grid: nearby beaches share one request

    def _fetch_marine(self, lat, lon):
        resp = requests.get(
            MARINE_URL,
            params={"latitude": lat, "longitude": lon, "timezone": "Africa/Johannesburg", "forecast_days": FORECAST_DAYS,
                    "daily": "wave_height_max,wave_period_max"},
            timeout=min(self.timeout, 3),
        )
        resp.raise_for_status()
        return parse_marine(resp.json()["daily"])

    def marine_for_places(self, places, iso_date):
        """{place_id: {"wave_height_m", "wave_period_s"}} for the beaches in `places` that have sea data that day.

        Missing data (inland, outage) just means no entry. After a failure the service is left alone for a few minutes."""
        beaches = [p for p in places if getattr(p, "category", None) == "Beach"]
        cells = {}
        for p in beaches:
            cells.setdefault(self._cell(p.latitude, p.longitude), []).append(p)

        now = time.time()
        todo = {cell: group[0] for cell, group in cells.items()
                if not (cell in self._marine_cache and now - self._marine_cache[cell][0] < MARINE_TTL)}
        if todo and now >= self._marine_down_until:
            def fetch(cell_place):
                cell, place = cell_place
                try:
                    return cell, self._fetch_marine(place.latitude, place.longitude)
                except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
                    print(f"[marine] unavailable: {exc}")
                    return cell, None

            with ThreadPoolExecutor(max_workers=min(6, len(todo))) as pool:
                for cell, days in pool.map(fetch, todo.items()):
                    if days is None:
                        self._marine_down_until = time.time() + MARINE_COOLDOWN
                    else:
                        self._marine_cache[cell] = (time.time(), days)

        out = {}
        for cell, group in cells.items():
            cached = self._marine_cache.get(cell)
            day = cached[1].get(iso_date) if cached else None
            if day:
                for p in group:
                    out[p.id] = day
        return out

    # ---- time of day ------------------------------------------------------------------------
    def today(self):
        return self.clock().astimezone(SAST).date().isoformat()

    def time_context(self, at=None, on=None):
        """South African time of day for the recommender.

        `at` ("HH:MM") is a what-if time; `on` ("YYYY-MM-DD") is a what-if day (noon unless `at` is given)."""
        now = self.clock().astimezone(SAST)
        if on and on != now.date().isoformat():
            now = datetime.fromisoformat(on).replace(hour=12, minute=0, tzinfo=SAST)
            at = at or "12:00"
        if at:
            hour, minute = (int(part) for part in at.split(":"))
            now = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        minutes = now.hour * 60 + now.minute
        return {
            "time": f"{now:%H:%M}",
            "minutes": minutes,
            "weekday": now.weekday(),                          # Monday = 0
            "date": f"{now:%Y-%m-%d}",
            "evening": minutes >= EVENING_START or minutes < NIGHT_END,
            "what_if": bool(at) or bool(on and on != self.today()),
            "timezone": "Africa/Johannesburg",
        }

    def check_loadshedding(self, mode="auto", hour=None):
        """Power status. Eskom's API is paid, so `auto` uses a simulated evening schedule.

        mode: "on" / "off" force a state (handy for demos), "auto" uses the simulated schedule (18:00-20:59 South African time).
        """
        if mode == "on":
            return True
        if mode == "off":
            return False
        hour = self.clock().astimezone(SAST).hour if hour is None else hour
        return 18 <= hour <= 20

    def get_context(self, lat, lon, loadshedding="auto", at=None, on=None):
        """Everything the recommender needs. `on` ranks for that day's forecast instead of today's weather."""
        future = bool(on and on != self.today())
        when = self.time_context(at, on if future else None)
        return {
            "weather": self.weather_for_date(lat, lon, on) if future else self.get_current_weather(lat, lon),
            "time": when,
            "loadshedding": self.check_loadshedding(loadshedding, hour=when["minutes"] // 60),
            "loadshedding_mode": loadshedding,
            "loadshedding_simulated": True,   # no live Eskom feed is wired up
        }
