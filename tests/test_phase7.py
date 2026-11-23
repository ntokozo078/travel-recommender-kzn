"""Phase 7: 7-day forecast, sea conditions for beaches, ranking for a chosen day."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests

from app import db
from app.models import Place
from app.services import FORECAST_DAYS, MARINE_COOLDOWN, SAST, ContextEngine, parse_forecast, parse_marine
from ml_engine.recommender import BIG_WAVES_M, score_place
from ml_engine.weather_rules import describe_weather

UTC = timezone.utc
MONDAY_NOON_UTC = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)          # 12:00 SAST on Monday 23 Nov 2026


class Reply:
    def __init__(self, payload=None, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def forecast_payload(start="2026-11-23", days=7, wet_on=()):
    dates = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(days)]
    return {"daily": {
        "time": dates,
        "weather_code": [63 if d in wet_on else 1 for d in dates],
        "temperature_2m_max": [20 + i for i in range(days)],
        "temperature_2m_min": [10 + i for i in range(days)],
        "precipitation_probability_max": [80 if d in wet_on else 10 for d in dates],
        "precipitation_sum": [5.0 if d in wet_on else 0.0 for d in dates],
    }}


def marine_payload(heights, start="2026-11-23"):
    dates = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(len(heights))]
    return {"daily": {"time": dates, "wave_height_max": heights, "wave_period_max": [9.0] * len(heights)}}


def engine():
    return ContextEngine(clock=lambda: MONDAY_NOON_UTC)


@pytest.fixture
def api_calls(monkeypatch):
    """Replace requests.get with a recorder; set `responder` to decide the reply."""
    calls = []
    box = SimpleNamespace(calls=calls, responder=lambda url, params: Reply(status=503))

    def fake_get(url, params=None, timeout=None, **kw):
        calls.append((url, dict(params or {})))
        result = box.responder(url, params or {})
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(requests, "get", fake_get)
    return box


# ---- parsing ---------------------------------------------------------------------------
def test_parse_forecast_builds_days_like_current_weather():
    days = parse_forecast(forecast_payload(wet_on={"2026-11-24"})["daily"])
    assert len(days) == 7 and days[0]["date"] == "2026-11-23" and days[0]["source"] == "forecast"
    wet = days[1]
    assert (wet["condition"], wet["is_wet"], wet["temp_c"], wet["temp_min_c"], wet["rain_chance_pct"], wet["rain_mm"]) == ("Rain", True, 21.0, 11.0, 80, 5.0)
    assert {"icon", "advice", "is_hot", "is_cold"} <= set(days[0])


def test_parse_forecast_drops_days_it_cannot_use_and_accepts_the_old_key():
    daily = {"time": ["2026-11-23", "2026-11-24", "2026-11-25"], "weathercode": [1, None, 3],
             "temperature_2m_max": [20, 21, None], "temperature_2m_min": [10, 11, 12]}
    days = parse_forecast(daily)
    assert [d["date"] for d in days] == ["2026-11-23"]                      # one missing a code, one missing a temperature
    assert days[0]["rain_chance_pct"] is None and days[0]["rain_mm"] is None  # unknown stays None, never 0


def test_parse_marine_skips_inland_nulls():
    assert parse_marine(marine_payload([1.4, None, 2.6])["daily"]) == {
        "2026-11-23": {"wave_height_m": 1.4, "wave_period_s": 9.0}, "2026-11-25": {"wave_height_m": 2.6, "wave_period_s": 9.0}}
    assert parse_marine(marine_payload([None] * 7)["daily"]) == {}


# ---- forecast service -----------------------------------------------------------------------
def test_forecast_is_fetched_once_and_cached(api_calls):
    api_calls.responder = lambda url, params: Reply(forecast_payload())
    e = engine()
    first = e.get_forecast(-29.85, 31.02)
    second = e.get_forecast(-29.86, 31.03)                                      # same 0.1 degree cell
    assert first["source"] == second["source"] == "live" and len(first["days"]) == 7
    assert len(api_calls.calls) == 1
    params = api_calls.calls[0][1]
    assert params["forecast_days"] == FORECAST_DAYS and "weather_code" in params["daily"]


def test_forecast_failure_gives_an_empty_fallback_and_is_retried(api_calls):
    api_calls.responder = lambda url, params: requests.ConnectionError("down")
    e = engine()
    assert e.get_forecast(-29.85, 31.02) == {"days": [], "source": "fallback"}
    api_calls.responder = lambda url, params: Reply(forecast_payload())
    assert e.get_forecast(-29.85, 31.02)["source"] == "live"                    # failures are not cached
    api_calls.responder = lambda url, params: Reply({"nope": 1})
    assert ContextEngine(clock=lambda: MONDAY_NOON_UTC).get_forecast(-28.0, 30.0)["source"] == "fallback"


def test_weather_for_date_uses_the_forecast_or_a_labelled_estimate(api_calls):
    api_calls.responder = lambda url, params: Reply(forecast_payload(wet_on={"2026-11-25"}))
    e = engine()
    wet = e.weather_for_date(-29.85, 31.02, "2026-11-25")
    assert wet["is_wet"] and wet["source"] == "forecast" and wet["date"] == "2026-11-25"
    missing = e.weather_for_date(-29.85, 31.02, "2026-12-25")                    # beyond the forecast window
    assert missing["source"] == "fallback" and missing["date"] == "2026-12-25" and not missing["is_wet"]
    api_calls.responder = lambda url, params: Reply(status=500)
    assert ContextEngine(clock=lambda: MONDAY_NOON_UTC).weather_for_date(-27, 30, "2026-11-25")["source"] == "fallback"


# ---- time of day for another date ---------------------------------------------------------------------
def test_time_context_for_a_future_day_uses_that_days_weekday_at_noon():
    e = engine()
    today = e.time_context()
    assert (today["date"], today["weekday"], today["what_if"]) == ("2026-11-23", 0, False)
    saturday = e.time_context(on="2026-11-28")
    assert (saturday["date"], saturday["weekday"], saturday["time"], saturday["what_if"], saturday["evening"]) == ("2026-11-28", 5, "12:00", True, False)
    night = e.time_context(at="21:30", on="2026-11-28")
    assert (night["time"], night["evening"], night["weekday"]) == ("21:30", True, 5)
    same = e.time_context(on="2026-11-23")
    assert same["what_if"] is False and same["time"] == "12:00"                  # "today" is just today (and it is noon)


def test_get_context_for_a_date_uses_the_forecast_and_that_days_hour(api_calls):
    api_calls.responder = lambda url, params: Reply(forecast_payload(wet_on={"2026-11-26"}))
    e = engine()
    ctx = e.get_context(-29.85, 31.02, "auto", at="19:00", on="2026-11-26")
    assert ctx["weather"]["is_wet"] and ctx["weather"]["date"] == "2026-11-26"
    assert ctx["time"]["date"] == "2026-11-26" and ctx["loadshedding"] is True      # simulated window includes 19:00
    today = e.get_context(-29.85, 31.02, "auto", on="2026-11-23")                    # today: current weather, not the forecast
    assert today["weather"].get("source") != "forecast"


# ---- sea conditions ------------------------------------------------------------------------------------------
def beach(pid, lat, lon, category="Beach"):
    return SimpleNamespace(id=pid, category=category, latitude=lat, longitude=lon)


def test_marine_only_for_beaches_sharing_requests_per_cell_and_caching(api_calls):
    api_calls.responder = lambda url, params: Reply(marine_payload([1.4, 2.8, 1.0]))
    e = engine()
    places = [beach(1, -29.85, 31.05), beach(2, -29.80, 31.00), beach(3, -30.30, 30.90), beach(4, -29.85, 31.02, "Culture")]
    out = e.marine_for_places(places, "2026-11-24")
    assert set(out) == {1, 2, 3} and out[1]["wave_height_m"] == 2.8 and out[3]["wave_height_m"] == 2.8
    assert len(api_calls.calls) == 2                                              # 1+2 share a half-degree cell, 3 is elsewhere
    assert all("marine-api" in url for url, _ in api_calls.calls)
    assert e.marine_for_places(places, "2026-11-23")[1]["wave_height_m"] == 1.4
    assert len(api_calls.calls) == 2                                              # cached
    assert e.marine_for_places(places, "2026-12-30") == {}                        # no data for that day: no entry, no guess


def test_inland_places_without_sea_data_get_nothing(api_calls):
    api_calls.responder = lambda url, params: Reply(marine_payload([None] * 7))
    assert engine().marine_for_places([beach(1, -29.45, 30.2)], "2026-11-23") == {}


def test_marine_failure_is_silent_and_the_service_is_left_alone_for_a_while(api_calls, monkeypatch):
    api_calls.responder = lambda url, params: requests.ConnectionError("down")
    e = engine()
    places = [beach(1, -29.85, 31.05)]
    assert e.marine_for_places(places, "2026-11-23") == {}
    assert len(api_calls.calls) == 1
    assert e.marine_for_places(places, "2026-11-23") == {} and len(api_calls.calls) == 1      # cooling down: no new request
    real = __import__("time").time
    monkeypatch.setattr("app.services.time.time", lambda: real() + MARINE_COOLDOWN + 1)
    api_calls.responder = lambda url, params: Reply(marine_payload([1.0] * 7))
    assert e.marine_for_places(places, "2026-11-23")[1]["wave_height_m"] == 1.0             # tried again after the pause


# ---- ranking with waves ----------------------------------------------------------------------------------------------
def fake_beach(**kw):
    base = dict(id=7, name="B", category="Beach", subcategory=None, is_indoor=False, has_generator=False, safety_score=None,
                latitude=-29.85, longitude=31.05, price_tier=None, opening_hours=None, opening_hours_raw=None,
                open_evening=None, open_late=None, min_age=None)
    base.update(kw)
    return SimpleNamespace(**base)


CALM_CTX = {"weather": describe_weather(1, 24), "loadshedding": False}


def test_big_waves_cost_points_and_small_ones_are_only_information():
    big = score_place(fake_beach(), CALM_CTX, {"marine": {7: {"wave_height_m": BIG_WAVES_M}}})
    small = score_place(fake_beach(), CALM_CTX, {"marine": {7: {"wave_height_m": 1.2}}})
    none = score_place(fake_beach(), CALM_CTX, {})
    assert [(r["text"], r["points"]) for r in big[1] if "aves" in r["text"]] == [("Big waves forecast (up to 2.5 m)", -3)]
    assert [(r["text"], r["points"]) for r in small[1] if "aves" in r["text"]] == [("Waves up to 1.2 m forecast", 0)]
    assert big[0] == none[0] - 3 and small[0] == none[0]


def test_only_beaches_get_wave_chips_and_unknown_means_no_chip():
    park = fake_beach(category="Nature")
    assert not any("aves" in r["text"] for r in score_place(park, CALM_CTX, {"marine": {7: {"wave_height_m": 4.0}}})[1])
    assert not any("aves" in r["text"] for r in score_place(fake_beach(), CALM_CTX, {"marine": {}})[1])


# ---- API ---------------------------------------------------------------------------------------------------------------
@pytest.fixture
def pinned_engine(monkeypatch):
    """The API with a fixed clock (Monday 23 Nov, noon) and a controllable forecast and sea."""
    state = SimpleNamespace(wet=set(), waves={})
    original_init = ContextEngine.__init__

    def init(self, *a, **kw):
        original_init(self, *a, **{**kw, "clock": lambda: MONDAY_NOON_UTC})

    monkeypatch.setattr(ContextEngine, "__init__", init)
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 24))
    monkeypatch.setattr(ContextEngine, "get_forecast", lambda self, lat, lon: {
        "source": "live", "days": parse_forecast(forecast_payload(wet_on=state.wet)["daily"])})
    monkeypatch.setattr(ContextEngine, "marine_for_places", lambda self, places, iso: {
        p.id: {"wave_height_m": state.waves[iso], "wave_period_s": 9.0} for p in places if p.category == "Beach" and iso in state.waves})
    return state


def test_forecast_endpoint(client, pinned_engine):
    data = client.get("/api/forecast").get_json()
    assert data["today"] == "2026-11-23" and data["source"] == "live" and len(data["days"]) == 7
    assert [d["date"] for d in data["days"]][:2] == ["2026-11-23", "2026-11-24"]


def test_forecast_endpoint_without_the_service_says_so(client):
    data = client.get("/api/forecast").get_json()                                       # network is blocked in tests
    assert data["days"] == [] and data["source"] == "fallback" and data["today"]


@pytest.mark.parametrize("bad", ["2026-11-22", "2026-11-30", "2026-12-24", "tomorrow", "2026-13-01", "26-11-24", "2026-11-24T10:00"])
def test_date_must_be_today_or_within_the_forecast(client, pinned_engine, bad):
    assert client.get(f"/api/recommend?date={bad}").status_code == 400


def test_date_edges_are_accepted(client, pinned_engine):
    assert client.get("/api/recommend?date=2026-11-23").status_code == 200
    assert client.get("/api/recommend?date=2026-11-29").status_code == 200              # day 7


def test_ranking_follows_the_forecast_for_the_chosen_day(client, pinned_engine, app):
    with app.app_context():
        indoor = Place(name="Test Gallery", category="Culture", latitude=-29.8, longitude=31.0, is_indoor=True, opening_hours="24 Hours")
        outdoor = Place(name="Test Garden", category="Nature", latitude=-29.8, longitude=31.1, is_indoor=False, opening_hours="24 Hours")
        db.session.add_all([indoor, outdoor])
        db.session.commit()
    pinned_engine.wet = {"2026-11-25"}

    def chips(query, name):
        data = client.get(f"/api/recommend?limit=60&{query}").get_json()
        item = next(r for r in data["results"] if r["name"] == name)
        return data["context"], {c["text"]: c["points"] for c in item["reasons"]}

    ctx, today = chips("", "Test Garden")
    assert today["Great weather to be outside"] == 3 and ctx["weather"].get("source") != "forecast"
    ctx, wet = chips("date=2026-11-25", "Test Garden")
    assert wet["Outdoors, so it may be wet"] == -3 and ctx["weather"]["date"] == "2026-11-25" and ctx["weather"]["source"] == "forecast"
    assert chips("date=2026-11-25", "Test Gallery")[1]["Indoors, so you stay dry"] == 5
    assert chips("date=2026-11-26", "Test Garden")[1]["Great weather to be outside"] == 3          # a dry day again


def test_opening_hours_are_checked_on_the_chosen_weekday(client, pinned_engine, app):
    with app.app_context():
        db.session.add(Place(name="Saturday Market", category="Shopping", latitude=-29.8, longitude=31.0, is_indoor=True, opening_hours="Sa 09:00-15:00"))
        db.session.commit()
    saturday = client.get("/api/recommend?category=Shopping&open_now=1&date=2026-11-28").get_json()
    assert "Saturday Market" in {r["name"] for r in saturday["results"]}
    assert saturday["context"]["time"]["weekday"] == 5
    friday = client.get("/api/recommend?category=Shopping&open_now=1&date=2026-11-27").get_json()
    assert "Saturday Market" not in {r["name"] for r in friday["results"]}
    today = client.get("/api/recommend?category=Shopping&open_now=1").get_json()                 # Monday
    assert "Saturday Market" not in {r["name"] for r in today["results"]}


def test_beach_results_carry_the_wave_forecast_for_that_day(client, pinned_engine, app):
    with app.app_context():
        db.session.add(Place(name="Test Beach", category="Beach", latitude=-29.85, longitude=31.05, is_indoor=False, opening_hours="24 Hours"))
        db.session.commit()
    pinned_engine.waves = {"2026-11-23": 1.1, "2026-11-25": 3.2}
    today = next(r for r in client.get("/api/recommend?category=Beach&limit=50").get_json()["results"] if r["name"] == "Test Beach")
    assert today["marine"]["wave_height_m"] == 1.1
    assert any(c["text"] == "Waves up to 1.1 m forecast" for c in today["reasons"])
    rough = next(r for r in client.get("/api/recommend?category=Beach&limit=50&date=2026-11-25").get_json()["results"] if r["name"] == "Test Beach")
    assert rough["marine"]["wave_height_m"] == 3.2
    assert any(c["text"].startswith("Big waves forecast") and c["points"] == -3 for c in rough["reasons"])
    assert "marine" not in next(r for r in client.get("/api/recommend?category=Culture&limit=5").get_json()["results"])


def test_everything_still_works_when_the_outside_services_are_down(client):
    data = client.get("/api/recommend?limit=5&date=" + (datetime.now(SAST).date() + timedelta(days=2)).isoformat()).get_json()
    assert data["context"]["weather"]["source"] == "fallback" and len(data["results"]) == 5
    assert all("marine" not in r for r in data["results"])


def test_page_has_the_trip_link_and_toast(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="#/itinerary"' in html and 'id="trip-badge"' in html and 'id="toast"' in html
