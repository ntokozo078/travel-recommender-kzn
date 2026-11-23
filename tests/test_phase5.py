"""Phase 5: filters behind the nightlife/entertainment planner (subcategory, region, open now/late, map points)."""
import pytest

from app import db
from app.models import Place
from app.services import ContextEngine
from ml_engine.weather_rules import describe_weather


@pytest.fixture(autouse=True)
def fake_weather(monkeypatch):
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 22))


def add(app, **kw):
    base = dict(category="Nightlife", latitude=-29.85, longitude=31.02, is_indoor=True)
    base.update(kw)
    with app.app_context():
        place = Place(**{**base})
        db.session.add(place)
        db.session.commit()
        return place.id


@pytest.fixture
def venues(app):
    """A small, known set of venues with different hours (all made up for the tests)."""
    return {
        "club": add(app, name="Late Club", subcategory="nightclub", region="Durban", opening_hours_raw="Mo-Su 20:00-04:00", open_evening=True, open_late=True),
        "pub": add(app, name="Early Pub", subcategory="pub", region="Midlands", opening_hours_raw="Mo-Su 11:00-22:00", open_evening=True, open_late=False),
        "bar": add(app, name="Mystery Bar", subcategory="bar", region="Durban"),                    # hours unknown
        "kino": add(app, name="Test Cinema", category="Entertainment", subcategory="cinema", region="Durban", opening_hours_raw="Mo-Su 10:00-23:30"),
        "early": add(app, name="Early Cinema", category="Entertainment", subcategory="cinema", region="Durban", opening_hours_raw="Mo-Su 10:00-23:00"),
        "text": add(app, name="Curated Style Bar", subcategory="bar", region="South Coast", opening_hours="09:00 - 17:00"),
    }


def names(client, query):
    data = client.get("/api/recommend?limit=50&" + query).get_json()
    return {r["name"] for r in data["results"]}, data


# ---- /api/filters -----------------------------------------------------------------------
def test_filters_list_subcategories_and_regions_with_counts(client, venues):
    data = client.get("/api/filters").get_json()
    nightlife = {s["slug"]: (s["label"], s["count"]) for s in data["subcategories"]["Nightlife"]}
    assert nightlife == {"nightclub": ("Nightclub", 1), "bar": ("Bar", 2), "pub": ("Pub", 1)}
    assert [s["slug"] for s in data["subcategories"]["Nightlife"]] == ["nightclub", "bar", "pub"]       # taxonomy order
    assert data["subcategories"]["Entertainment"] == [{"slug": "cinema", "label": "Cinema", "count": 2}]
    regions = {r["name"]: r["count"] for r in data["regions"]}
    assert regions == {"Durban": 4, "South Coast": 1, "Midlands": 1}
    assert [r["name"] for r in data["regions"]] == ["Durban", "South Coast", "Midlands"]               # taxonomy order


def test_filters_never_offer_empty_options(client):
    data = client.get("/api/filters").get_json()
    assert data["subcategories"] == {} and data["regions"] == []


# ---- subcategory + region ---------------------------------------------------------------------
def test_subcategory_and_region_filters(client, venues):
    found, _ = names(client, "category=Nightlife&subcategory=bar")
    assert found == {"Mystery Bar", "Curated Style Bar"}
    found, _ = names(client, "category=Nightlife&subcategory=bar&region=Durban")
    assert found == {"Mystery Bar"}
    found, _ = names(client, "region=Midlands")
    assert found == {"Early Pub"}
    found, data = names(client, "subcategory=cinema")
    assert found == {"Test Cinema", "Early Cinema"} and data["total"] == 2


def test_bad_subcategory_or_region_is_a_400(client):
    assert client.get("/api/recommend?subcategory=strip_club").status_code == 400
    assert client.get("/api/recommend?region=Atlantis").status_code == 400
    assert client.get("/api/recommend?subcategory=&region=").status_code == 200           # empty = no filter


# ---- open now / open late: only places whose hours prove it ----------------------------------------
def test_open_now_keeps_only_places_whose_hours_confirm_it(client, venues):
    found, _ = names(client, "category=Nightlife&open_now=1&at=21:30")
    assert found == {"Late Club", "Early Pub"}                                # unknown-hours bar is NOT assumed open
    found, _ = names(client, "category=Nightlife&open_now=1&at=22:00")
    assert found == {"Late Club"}                                              # the pub closes at 22:00 (end is exclusive)
    found, _ = names(client, "category=Nightlife&open_now=1&at=12:00")
    assert found == {"Early Pub", "Curated Style Bar"}                         # curated-style text hours work too
    found, _ = names(client, "category=Nightlife&open_now=1&at=03:00")
    assert found == {"Late Club"}                                              # overnight opening


def test_open_now_follows_the_what_if_time_for_the_whole_ranking(client, venues):
    found, evening = names(client, "category=Entertainment&open_now=1&at=22:30")
    assert evening["context"]["time"]["time"] == "22:30" and evening["context"]["time"]["what_if"] is True
    assert "Test Cinema" in found and "Early Cinema" in found                  # both run until 23:00 or later
    found, late = names(client, "category=Entertainment&open_now=1&at=23:15")
    assert "Test Cinema" in found and "Early Cinema" not in found


def test_open_late_uses_the_flag_or_the_listed_text(client, venues):
    found, _ = names(client, "category=Nightlife&open_late=1")
    assert found == {"Late Club"}                                              # pub closes at 22:00, bar unknown, text closes 17:00
    found, _ = names(client, "subcategory=cinema&open_late=1")
    assert found == {"Test Cinema"}                      # no flag stored: parsed from the text; closing at exactly 23:00 is not "late"


def test_open_filters_combine_with_other_filters(client, venues):
    found, _ = names(client, "category=Nightlife&region=Durban&open_now=1&open_late=1&at=23:30")
    assert found == {"Late Club"}
    found, data = names(client, "category=Nightlife&subcategory=pub&open_late=1")
    assert found == set() and data["total"] == 0 and data["results"] == []


def test_open_now_with_nothing_listed_returns_an_empty_list_not_an_error(client):
    data = client.get("/api/recommend?open_now=1&category=Nightlife").get_json()
    assert data["results"] == [] and data["total"] == 0


# ---- map points ---------------------------------------------------------------------------------------
def test_points_return_every_match_beyond_the_page(client, venues):
    data = client.get("/api/recommend?category=Nightlife&limit=1&points=1").get_json()
    assert len(data["results"]) == 1 and data["total"] == 4
    assert len(data["points"]) == 4
    assert set(data["points"][0]) == {"id", "name", "category", "latitude", "longitude"}
    assert data["points"][0]["name"] == data["results"][0]["name"]            # same ranking order


def test_points_are_only_sent_when_asked(client, venues):
    assert client.get("/api/recommend?category=Nightlife").get_json()["points"] is None


# ---- unknown stays unknown in the API ----------------------------------------------------------------------
def test_unknown_address_and_hours_are_null_not_made_up(client, venues):
    data = client.get("/api/recommend?category=Nightlife&subcategory=bar&region=Durban").get_json()
    place = data["results"][0]
    assert place["address"] is None and place["opening_hours"] is None and place["opening_hours_raw"] is None
    assert place["website"] is None and place["phone"] is None and place["min_age"] is None
    assert place["safety_rated"] is False and place["subcategory_label"] == "Bar"


# ---- page ------------------------------------------------------------------------------------------------------
def test_page_loads_clustering_and_credits_openstreetmap(client):
    html = client.get("/").get_data(as_text=True)
    assert "leaflet.markercluster" in html and "MarkerCluster.Default.css" in html
    assert "OpenStreetMap contributors" in html and "Open Database Licence" in html
