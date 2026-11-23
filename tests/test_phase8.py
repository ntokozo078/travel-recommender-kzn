"""Phase 8: SEO plumbing, the no-JavaScript summary, offline ETL from a fixture file,
oldest-schema migration safety, the API contract and the recommender's basic guarantees."""
import re
import sqlite3
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from app import db
from app.models import Place, SchemaMigration
from app.services import ContextEngine
from etl_pipeline import pipeline
from ml_engine.recommender import recommend_places
from ml_engine.weather_rules import describe_weather
from tests.conftest import ROOT, make_app

FIXTURE = ROOT / "tests" / "fixtures" / "overpass_sample.json"
JS = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")


# ---- head: title, description, Open Graph, canonical ------------------------------------------------
def test_page_head_has_description_open_graph_and_canonical(client):
    html = client.get("/").get_data(as_text=True)
    assert html.count("<title>") == 1 and "KwaZulu-Natal trip planner" in html
    for needle in ('name="description"', 'property="og:type" content="website"', 'property="og:site_name"',
                   'property="og:title"', 'property="og:description"', 'name="twitter:card"', 'rel="canonical"'):
        assert needle in html, needle
    assert 'property="og:url" content="http://localhost/"' in html and 'rel="canonical" href="http://localhost/"' in html
    assert "{{" not in html and "{%" not in html                                  # no template leftovers


def test_unknown_paths_still_serve_the_page_with_a_404(client):
    response = client.get("/no/such/page")
    assert response.status_code == 404 and "<noscript>" in response.get_data(as_text=True)
    assert client.get("/api/nope").status_code == 404 and client.get("/api/nope").is_json


# ---- sitemap + robots -----------------------------------------------------------------------------------
def test_robots_txt(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200 and response.mimetype == "text/plain"
    lines = response.get_data(as_text=True).splitlines()
    assert "User-agent: *" in lines and "Allow: /" in lines and "Disallow: /api/" in lines
    assert "Sitemap: http://localhost/sitemap.xml" in lines


def test_sitemap_xml_is_valid_and_lists_the_site(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200 and response.mimetype == "application/xml"
    root = ET.fromstring(response.get_data())
    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"
    locs = [el.text for el in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert locs == ["http://localhost/"] and not any("#" in loc for loc in locs)     # fragments are ignored by search engines


def test_sitemap_escapes_the_host(client):
    response = client.get("/sitemap.xml", base_url="http://exa&mple.test/")
    ET.fromstring(response.get_data())                                                # still well-formed XML


# ---- noscript summary ---------------------------------------------------------------------------------------
def test_noscript_summary_has_real_content(real_client):
    html = real_client.get("/").get_data(as_text=True)
    summary = html[html.index("<noscript>"):html.index("</noscript>")]
    assert "needs JavaScript" in summary
    for label in ("Clans", "Herbs", "Foods", "Rituals", "Dance", "Dress", "Beads", "Places"):
        assert f"<strong>{label}</strong>" in summary
    assert re.search(r"<li>Beach: \d+</li>", summary)
    for number in ("112", "10111", "10177"):
        assert f'href="tel:{number}"' in summary
    assert "check locally" in summary.lower()


def test_noscript_lists_places_to_stay_separately(app, client):
    with app.app_context():
        db.session.add(Place(name="Test Hotel", category="Stay", subcategory="hotel", latitude=0, longitude=0))
        db.session.commit()
    summary = client.get("/").get_data(as_text=True)
    summary = summary[summary.index("<noscript>"):summary.index("</noscript>")]
    assert "<li>Stay: 1 (hotels, guest houses" in summary
    total = int(re.search(r"<p>(\d+) places to visit", summary).group(1))
    with app.app_context():
        assert total == Place.query.filter(Place.category != "Stay").count()          # hotels are not "places to visit"


def test_noscript_summary_survives_missing_data(client):
    """The test app has no data/info.json: the page must still render (just without the emergency numbers)."""
    html = client.get("/").get_data(as_text=True)
    assert "<noscript>" in html and "tel:" not in html[html.index("<noscript>"):html.index("</noscript>")]


def test_noscript_content_is_escaped(app, client):
    with app.app_context():
        db.session.add(Place(name="x", category="Beach", latitude=0, longitude=0))
        db.session.commit()
    html = client.get("/").get_data(as_text=True)
    assert "<script" not in html[html.index("<noscript>"):html.index("</noscript>")]


# ---- titles follow the route (checked in the script, which has no test runner here) -------------------------
def test_every_view_sets_its_own_title_through_one_function():
    assert len(re.findall(r"document\.title\s*=", JS)) == 1                    # only inside setMeta
    for expected in ('setMeta("")', 'setMeta("My trip"', 'setMeta("Travel info for KwaZulu-Natal"',
                     "Zulu heritage", "tripMeta(state.trip.category)", "clan`, `Izithakazelo"):
        assert expected in JS, expected
    assert 'meta[property="og:title"]' in JS and 'meta[name="description"]' in JS


def test_skip_link_no_longer_breaks_the_hash_router():
    assert 'skip-link").addEventListener("click"' in JS and "e.preventDefault()" in JS


# ---- CI ------------------------------------------------------------------------------------------------------------
def test_github_actions_runs_pytest_on_push():
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "on:\n  push:" in workflow and "pull_request" in workflow
    assert "actions/checkout@v4" in workflow and "actions/setup-python@v5" in workflow
    assert "pip install -r requirements.txt pytest" in workflow and "python -m pytest" in workflow


# ---- ETL mapping from a fixture file (offline) --------------------------------------------------------------------
@pytest.fixture(scope="module")
def fixture_rows():
    return pipeline.transform(pipeline.load_candidates_file(FIXTURE))


def by_name(rows):
    return {r["name"]: r for r in rows}


def test_fixture_file_is_mapped_end_to_end(fixture_rows):
    rows = by_name(fixture_rows)
    assert {n: (r["category"], r["subcategory"]) for n, r in rows.items()} == {
        "Fixture Club": ("Nightlife", "nightclub"), "Fixture Pub": ("Nightlife", "pub"),
        "Fixture Cinema": ("Entertainment", "cinema"), "Mama's Shisa Nyama": ("Nightlife", "shisa_nyama"),
        "Fixture Casino": ("Entertainment", "casino"), "Fixture Karting": ("Entertainment", "go_karting"),
        "Fixture Water Park": ("Entertainment", "water_park"), "Fixture Hotel": ("Stay", "hotel"),
        "Fixture Chalet": ("Stay", "chalet"), "Fixture Museum": ("Culture", None), "Odd Hours Bar": ("Nightlife", "bar"),
        "Fixture Theatre": ("Entertainment", "theatre"), "Chain Bar": ("Nightlife", "bar"),
        "Fixture Zoo": ("Nature", None), "Fixture Camp": ("Stay", "camp_site"),
    }
    assert len(fixture_rows) == 16                                                   # 15 names, "Chain Bar" kept twice


def test_fixture_skips_unnamed_unmapped_accommodation_we_skip_and_missing_coordinates(fixture_rows):
    names = {r["name"] for r in fixture_rows}
    assert not names & {"Fixture Motel", "Fixture Bench", "No Coordinates Bar"} and "" not in names
    assert all(r["name"] for r in fixture_rows)


def test_fixture_duplicates_and_chains(fixture_rows):
    cinemas = [r for r in fixture_rows if r["name"] == "Fixture Cinema"]
    assert len(cinemas) == 1 and cinemas[0]["osm_id"] == "way/2001"                 # the richer way beat the bare node
    assert cinemas[0]["website"] == "https://www.cinema.example" and cinemas[0]["phone"] == "+27 31 111 1111"
    chains = [r for r in fixture_rows if r["name"] == "Chain Bar"]
    assert sorted(r["osm_id"] for r in chains) == ["node/1015", "node/1016"]         # same name, far apart: two venues


def test_fixture_details_and_unknowns(fixture_rows):
    rows = by_name(fixture_rows)
    club = rows["Fixture Club"]
    assert (club["open_evening"], club["open_late"], club["min_age"], club["website"], club["region"]) == (True, True, 18, "https://club.example/", "Durban")
    pub = rows["Fixture Pub"]
    assert pub["address"] == "5 Test Road, Testville" and pub["tags"] == "osm:amenity=pub,live_music,outdoor_seating"
    assert (pub["open_evening"], pub["open_late"]) == (True, False)
    assert (rows["Fixture Casino"]["open_evening"], rows["Fixture Casino"]["open_late"]) == (True, True)
    odd = rows["Odd Hours Bar"]
    assert (odd["open_evening"], odd["open_late"], odd["opening_hours_raw"]) == (None, None, "sunrise-sunset")
    assert rows["Fixture Hotel"]["category"] == "Stay"                                 # a hotel with a bar is a hotel
    for r in fixture_rows:
        assert r["safety_score"] is None and r["price_tier"] is None and r["source"] == "osm"
    assert rows["Fixture Camp"]["is_indoor"] is False and rows["Fixture Hotel"]["is_indoor"] is True


def test_fixture_loads_idempotently_into_a_database(app, fixture_rows):
    from etl_pipeline.loader import load_rows
    with app.app_context():
        before = Place.query.count()
        assert load_rows(fixture_rows)["inserted"] == 16
        assert load_rows(fixture_rows)["inserted"] == 0
        assert Place.query.count() == before + 16


# ---- migration safety: the very first schema --------------------------------------------------------------------------
FIRST_SCHEMA = """
CREATE TABLE places (
    id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, description TEXT, category VARCHAR(50),
    address VARCHAR(200), opening_hours VARCHAR(100), image_url VARCHAR(500),
    latitude FLOAT NOT NULL, longitude FLOAT NOT NULL, is_indoor BOOLEAN, has_generator BOOLEAN,
    safety_score FLOAT, price_tier VARCHAR(10), last_updated DATETIME
);
"""


@pytest.fixture
def first_version_db(tmp_path):
    con = sqlite3.connect(tmp_path / "test.db")
    con.executescript(FIRST_SCHEMA)
    con.executemany(
        "INSERT INTO places (id, name, category, address, opening_hours, latitude, longitude, is_indoor, has_generator, safety_score, price_tier)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(1, "Old Beach", "Beach", "Somewhere", "24 Hours", -29.8, 31.0, 0, 0, 4.5, "$$"),
         (2, "Old Museum", "Culture", None, None, -29.9, 31.1, 1, 0, 3.0, "$$")])
    con.commit()
    con.close()
    return tmp_path


def test_the_very_first_database_upgrades_without_losing_anything(first_version_db, data_dir):
    app = make_app(first_version_db, data_dir)
    try:
        with app.app_context():
            places = {p.name: p for p in Place.query.all()}
            assert set(places) == {"Old Beach", "Old Museum"}                                  # nothing deleted or re-seeded
            beach = places["Old Beach"]
            assert (beach.address, beach.opening_hours, beach.safety_score) == ("Somewhere", "24 Hours", 4.5)
            assert beach.price_tier is None                                                    # placeholder cleared
            assert beach.source is None and beach.region is None and beach.osm_id is None     # new columns start unknown
            assert beach.to_dict()["safety_rated"] is True and places["Old Museum"].to_dict()["address"] is None
            from app.migrations import MIGRATIONS
            assert {m.key for m in SchemaMigration.query.all()} == {key for key, _ in MIGRATIONS}
        con = sqlite3.connect(first_version_db / "test.db")
        columns = {row[1] for row in con.execute("PRAGMA table_info(places)")}
        con.close()
        assert {"source", "subcategory", "region", "website", "phone", "min_age", "open_evening", "open_late",
                "opening_hours_raw", "tags", "osm_id"} <= columns
    finally:
        with app.app_context():
            db.engine.dispose()


def test_an_upgraded_first_database_works_through_the_api(first_version_db, data_dir, monkeypatch):
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 24))
    app = make_app(first_version_db, data_dir)
    try:
        client = app.test_client()
        data = client.get("/api/recommend?limit=10").get_json()
        assert {r["name"] for r in data["results"]} == {"Old Beach", "Old Museum"}
        assert client.get("/api/filters").status_code == 200 and client.get("/api/categories").status_code == 200
        assert client.get("/").status_code == 200
        second = make_app(first_version_db, data_dir)                                          # a second start changes nothing
        with second.app_context():
            assert Place.query.count() == 2
            db.engine.dispose()
    finally:
        with app.app_context():
            db.engine.dispose()


# ---- API contract (the front end depends on these shapes) ---------------------------------------------------------------
@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 24))


PLACE_KEYS = {"id", "name", "description", "category", "address", "opening_hours", "image_url", "latitude", "longitude",
              "is_indoor", "has_generator", "safety_score", "price_tier", "source", "safety_rated", "subcategory",
              "subcategory_label", "region", "website", "phone", "min_age", "open_evening", "open_late",
              "opening_hours_raw", "tags", "score", "reasons", "distance_km"}


def test_recommend_response_shape(client, calm):
    data = client.get("/api/recommend?limit=3&points=1").get_json()
    assert set(data) == {"context", "category", "vibes", "tourist_mode", "total", "results", "points"}
    assert set(data["context"]) == {"weather", "time", "loadshedding", "loadshedding_mode", "loadshedding_simulated"}
    assert set(data["context"]["time"]) == {"time", "minutes", "weekday", "date", "evening", "what_if", "timezone"}
    for item in data["results"]:
        assert PLACE_KEYS <= set(item)
        assert all(set(r) == {"text", "tone", "points"} for r in item["reasons"])
        assert item["score"] == round(sum(r["points"] for r in item["reasons"]), 1) or item["reasons"] == []


def test_recommend_limits_filters_and_stable_order(client, calm):
    first = client.get("/api/recommend?limit=5").get_json()["results"]
    again = client.get("/api/recommend?limit=5").get_json()["results"]
    assert [r["id"] for r in first] == [r["id"] for r in again] and len(first) == 5
    scores = [r["score"] for r in client.get("/api/recommend?limit=50").get_json()["results"]]
    assert scores == sorted(scores, reverse=True)
    assert client.get("/api/recommend?limit=0").get_json()["results"].__len__() == 1       # limit is clamped to 1..50
    assert len(client.get("/api/recommend?limit=999").get_json()["results"]) <= 50
    assert client.get("/api/recommend?limit=abc").status_code == 200


# ---- recommender guarantees ------------------------------------------------------------------------------------------------
def fake(pid, name, category="Culture", **kw):
    base = dict(id=pid, name=name, category=category, subcategory=None, is_indoor=True, has_generator=False, safety_score=None,
                latitude=-29.85, longitude=31.02, price_tier=None, opening_hours=None, opening_hours_raw=None,
                open_evening=None, open_late=None, min_age=None)
    base.update(kw)
    ns = SimpleNamespace(**base)
    ns.to_dict = lambda: {"id": ns.id, "name": ns.name, "category": ns.category}
    return ns


def test_recommender_never_drops_a_place_and_breaks_ties_by_name():
    context = {"weather": describe_weather(63, 15), "loadshedding": True}
    places = [fake(1, "Zeta"), fake(2, "Alpha"), fake(3, "Mid", has_generator=True), fake(4, "Out", is_indoor=False)]
    ranked = recommend_places(places, {}, context)
    assert len(ranked) == 4
    assert [r["name"] for r in ranked] == ["Mid", "Alpha", "Zeta", "Out"]                 # best first; equal scores alphabetical
    assert recommend_places([], {}, context) == []
