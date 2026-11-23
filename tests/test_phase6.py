"""Phase 6: places to stay, and the practical travel-info content."""
import json
import re
from types import SimpleNamespace

import pytest

from app import db
from app.models import Place
from app.services import ContextEngine
from app.taxonomy import CATEGORIES, SUBCATEGORIES
from etl_pipeline import osm_mapping as om
from etl_pipeline import overpass, pipeline, regions
from ml_engine.recommender import score_place
from ml_engine.weather_rules import describe_weather
from tests.conftest import ROOT


@pytest.fixture(autouse=True)
def fake_weather(monkeypatch):
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 22))


def el(osm_id, name, lat=-29.85, lon=31.02, **tags):
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "tags": dict(tags, name=name), "_region": "Durban"}


# ---- OSM tags -> Stay -----------------------------------------------------------------------
@pytest.mark.parametrize("tourism, sub, indoor", [
    ("hotel", "hotel", True), ("guest_house", "guest_house", True), ("hostel", "hostel", True),
    ("chalet", "chalet", True), ("camp_site", "camp_site", False),
])
def test_accommodation_tags_become_stay(tourism, sub, indoor):
    assert om.classify({"tourism": tourism, "name": "X"})[:3] == ("Stay", sub, indoor)


def test_other_lodging_is_still_skipped():
    for tourism in ("apartment", "motel", "caravan_site", "alpine_hut", "wilderness_hut", "camp_pitch"):
        assert om.classify({"tourism": tourism, "name": "X"}) is None


def test_a_hotel_with_a_bar_is_a_hotel_not_nightlife():
    assert om.classify({"tourism": "hotel", "amenity": "bar", "name": "Grand Hotel"})[:2] == ("Stay", "hotel")


def test_stay_is_a_category_with_the_five_subcategories():
    assert "Stay" in CATEGORIES
    assert set(SUBCATEGORIES["Stay"]) == {"hotel", "guest_house", "hostel", "chalet", "camp_site"}


def test_the_query_asks_for_the_five_tourism_values():
    query = overpass.build_query(regions.CHUNKS[0].area_id, keys=("tourism",))
    for value in ("hotel", "guest_house", "hostel", "chalet", "camp_site"):
        assert value in query
    assert "apartment" not in query and "motel" not in query


def test_transform_builds_stay_rows_without_inventing_details():
    row = pipeline.transform([el(1, "Sea View Guest House", tourism="guest_house")])[0]
    assert (row["category"], row["subcategory"], row["is_indoor"]) == ("Stay", "guest_house", True)
    assert row["description"].startswith("Guest house in the Durban region")
    for unknown in ("price_tier", "safety_score", "website", "phone", "min_age", "address"):
        assert row[unknown] is None


# ---- the cache never serves results made by an older query ------------------------------------------
def test_cache_from_a_different_query_is_refetched_but_offline_still_uses_it(tmp_path):
    chunk = regions.CHUNKS[1]
    path = overpass.cache_file(tmp_path, chunk)
    overpass.write_cache(path, chunk, [el(1, "Old Bar", amenity="bar")], qhash="oldhash")
    assert overpass.read_cache(path, 7, qhash=overpass.query_hash(chunk)) is None          # query changed: stale
    assert overpass.read_cache(path, 7, qhash="oldhash") is not None
    calls = []

    def fetch(c, log=print):
        calls.append(c.name)
        return [el(2, "New Hotel", tourism="hotel")]

    elements, _ = overpass.extract_all([chunk], tmp_path, fetch=fetch, sleep=lambda s: None, log=lambda *_: None)
    assert calls == [chunk.name] and elements[0]["id"] == 2
    overpass.extract_all([chunk], tmp_path, fetch=fetch, sleep=lambda s: None, log=lambda *_: None)
    assert calls == [chunk.name]                                                          # now fresh and matching
    overpass.write_cache(path, chunk, [el(3, "Offline", amenity="bar")], qhash="oldhash")
    offline, failed = overpass.extract_all([chunk], tmp_path, offline=True, log=lambda *_: None)
    assert failed == [] and offline[0]["id"] == 3                                         # offline mode takes what it has


def test_cache_files_without_a_hash_are_treated_as_stale(tmp_path):
    chunk = regions.CHUNKS[1]
    path = overpass.cache_file(tmp_path, chunk)
    overpass.write_cache(path, chunk, [])                                                  # the old format: no hash
    assert overpass.read_cache(path, 7, qhash=overpass.query_hash(chunk)) is None


# ---- Stay is not a "thing to do" -----------------------------------------------------------------------
@pytest.fixture
def stays(app):
    with app.app_context():
        for i, (name, region, sub, lat) in enumerate([
            ("Hotel A", "Durban", "hotel", -29.80), ("Guest House B", "Durban", "guest_house", -29.90),
            ("Chalet C", "Drakensberg", "chalet", -29.00), ("Camp D", "South Coast", "camp_site", -30.50),
        ]):
            db.session.add(Place(name=name, category="Stay", subcategory=sub, region=region, latitude=lat, longitude=31.0,
                                 is_indoor=sub != "camp_site", has_generator=True, source="osm"))
        db.session.commit()


def test_stays_are_left_out_of_the_all_ranking(client, stays):
    everything = {r["name"] for r in client.get("/api/recommend?limit=50").get_json()["results"]}
    assert not everything & {"Hotel A", "Guest House B", "Chalet C", "Camp D"}
    assert client.get("/api/recommend?category=All&limit=50").get_json()["total"] == client.get("/api/recommend?limit=50").get_json()["total"]


def test_choosing_stay_lists_only_places_to_sleep(client, stays):
    data = client.get("/api/recommend?category=Stay&limit=50").get_json()
    assert {r["name"] for r in data["results"]} == {"Hotel A", "Guest House B", "Chalet C", "Camp D"}
    assert data["total"] == 4
    assert {r["region"] for r in data["results"]} == {"Durban", "Drakensberg", "South Coast"}
    found = client.get("/api/recommend?category=Stay&subcategory=hotel&region=Durban").get_json()["results"]
    assert [r["name"] for r in found] == ["Hotel A"]


def test_categories_say_stay_is_not_part_of_all(client, stays):
    cats = {c["name"]: c for c in client.get("/api/categories").get_json()}
    assert cats["Stay"]["count"] == 4 and cats["Stay"]["in_all"] is False
    assert cats["Beach"]["in_all"] is True


def test_filters_offer_stay_subcategories_and_regions(client, stays):
    data = client.get("/api/filters").get_json()
    assert {s["slug"] for s in data["subcategories"]["Stay"]} == {"hotel", "guest_house", "chalet", "camp_site"}
    assert "Drakensberg" in {r["name"] for r in data["regions"]}


def test_near_places_skip_hotels_unless_asked(client, stays):
    near = client.get("/api/places/near?lat=-29.80&lon=31.0&limit=10").get_json()["results"]
    assert "Hotel A" not in {r["name"] for r in near}
    with_stays = client.get("/api/places/near?lat=-29.80&lon=31.0&limit=3&include_stays=1").get_json()["results"]
    assert with_stays[0]["name"] == "Hotel A"


def test_stay_ranking_ignores_weather_and_time_but_not_power_or_distance():
    def stay(**kw):
        base = dict(id=1, name="S", category="Stay", subcategory="hotel", is_indoor=True, has_generator=False, safety_score=None,
                    latitude=-29.85, longitude=31.02, price_tier=None, opening_hours=None, opening_hours_raw=None,
                    open_evening=None, open_late=None, min_age=None)
        base.update(kw)
        return SimpleNamespace(**base)

    wet_evening = {"weather": describe_weather(63, 15), "loadshedding": False,
                   "time": {"minutes": 21 * 60, "weekday": 2, "evening": True}}
    sunny_day = {"weather": describe_weather(0, 25), "loadshedding": False,
                 "time": {"minutes": 12 * 60, "weekday": 2, "evening": False}}
    assert score_place(stay(), wet_evening, {})[0] == score_place(stay(), sunny_day, {})[0] == 0
    out = {"weather": describe_weather(0, 25), "loadshedding": True}
    assert score_place(stay(has_generator=True), out, {})[0] == 5 and score_place(stay(), out, {})[0] == -5
    near = score_place(stay(latitude=-29.85), sunny_day, {"lat": -29.85, "lon": 31.02})[0]
    far = score_place(stay(latitude=-27.0), sunny_day, {"lat": -29.85, "lon": 31.02})[0]
    assert near > far


# ---- travel info content ----------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def info():
    return json.loads((ROOT / "data" / "info.json").read_text(encoding="utf-8"))


def all_text(info):
    parts = [info["title"], info["subtitle"], info["disclaimer"]]
    for sec in info["sections"]:
        parts += [sec["title"], sec.get("intro", "")]
        parts += [n["label"] + " " + n.get("note", "") for n in sec.get("numbers", [])]
        parts += [i["title"] + " " + i["text"] for i in sec.get("items", [])]
    return "\n".join(parts)


def test_info_endpoint_serves_the_file(real_client, info):
    assert real_client.get("/api/info").get_json() == info


def test_info_endpoint_is_a_json_404_when_the_file_is_missing(client):
    response = client.get("/api/info")
    assert response.status_code == 404 and "error" in response.get_json()


def test_info_has_every_requested_topic(info):
    ids = {s["id"] for s in info["sections"]}
    assert {"emergency", "getting-around", "money", "sim-data", "etiquette", "power-water", "stay"} <= ids
    text = all_text(info).lower()
    for phrase in ("king shaka", "e-hailing", "car hire", "minibus taxi", "atm", "tipping", "sim card",
                   "ask before you photograph", "village", "load-shedding", "water outage", "check locally"):
        assert phrase in text, phrase


def test_only_the_three_known_emergency_numbers_are_listed(info):
    numbers = [n["number"] for s in info["sections"] for n in s.get("numbers", [])]
    assert numbers == ["112", "10111", "10177"]


def test_no_other_phone_numbers_or_prices_appear(info):
    text = all_text(info)
    digits = set(re.findall(r"\d{3,}", text)) - {"112", "10111", "10177"}
    assert not digits, f"unexpected long numbers: {digits}"
    assert not re.search(r"\bR\s?\d", text), "prices (R 100) must not appear"
    assert "$" not in text and "€" not in text and "£" not in text
    assert "+27" not in text and "0800" not in text


def test_every_item_is_well_formed_and_uncertain_ones_are_flagged(info):
    for sec in info["sections"]:
        assert sec["title"] and sec["icon"] and (sec.get("items") or sec.get("numbers"))
        for item in sec.get("items", []):
            assert set(item) == {"title", "text", "check"} and isinstance(item["check"], bool)
            assert item["title"].strip() and len(item["text"]) > 20
    flagged = sum(i["check"] for s in info["sections"] for i in s.get("items", []))
    assert flagged >= 10                                                       # most facts say "check locally"


def test_internal_links_point_at_real_pages(info):
    for sec in info["sections"]:
        if "link" in sec:
            assert re.fullmatch(r"#/(heritage/\w+|trip\?category=\w+|info)", sec["link"]["href"])


def test_page_has_an_info_link_in_the_navigation(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="#/info"' in html


def test_stays_get_no_filler_reason_chip(client, stays):
    results = client.get("/api/recommend?category=Stay&limit=4").get_json()["results"]
    assert results and all(r["reasons"] == [] for r in results)          # nothing to explain, so nothing is claimed


def test_stay_regions_can_be_requested_one_at_a_time(client, stays):
    """The Stay view asks for each region separately, so every region is represented."""
    drakensberg = client.get("/api/recommend?category=Stay&region=Drakensberg&limit=12&points=1").get_json()
    assert [r["name"] for r in drakensberg["results"]] == ["Chalet C"] and drakensberg["total"] == 1
    assert [p["name"] for p in drakensberg["points"]] == ["Chalet C"]
    assert client.get("/api/recommend?category=Stay&region=Zululand").get_json()["total"] == 0
