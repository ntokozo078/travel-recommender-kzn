"""Phase 2: taxonomy, new Place columns, safe migration, NULL safety = "not rated"."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import db
from app.models import Place, SchemaMigration
from app.overrides import apply_overrides
from app.taxonomy import CATEGORIES, REGIONS, SUBCATEGORIES, SUBCATEGORY_LABELS, is_valid_subcategory
from etl_pipeline import pipeline
from ml_engine.recommender import recommend_places
from ml_engine.weather_rules import describe_weather
from tests.conftest import make_app, write_data

NEW_COLUMNS = {"subcategory", "region", "website", "phone", "min_age", "open_evening",
               "open_late", "opening_hours_raw", "tags"}


# ---- taxonomy ------------------------------------------------------------------
def test_categories_keep_the_old_ones_and_add_nightlife():
    for old in ("Beach", "Nature", "Adventure", "Culture", "Food", "Shopping", "Entertainment"):
        assert old in CATEGORIES
    assert "Nightlife" in CATEGORIES


def test_requested_subcategories_exist():
    assert set(SUBCATEGORIES["Nightlife"].values()) == {
        "Nightclub", "Bar", "Pub", "Live music", "Lounge", "Shisa nyama", "Brewery / taproom"}
    assert set(SUBCATEGORIES["Entertainment"].values()) == {
        "Cinema", "Theatre", "Casino", "Bowling", "Ice skating", "Arcade", "Comedy", "Mini golf",
        "Go-karting", "Water park", "Amusement park", "Stadium / events venue", "Music venue"}
    assert set(SUBCATEGORIES["Stay"].values()) == {"Hotel", "Guest house", "Hostel", "Chalet", "Camp site"}
    assert len(SUBCATEGORY_LABELS) == 37                     # slugs are unique across categories
    assert is_valid_subcategory("nightclub") and not is_valid_subcategory("strip_club")


def test_regions_include_the_requested_ones():
    for region in ("Durban", "North Coast", "South Coast", "Midlands", "Drakensberg", "Zululand", "Pietermaritzburg"):
        assert region in REGIONS


# ---- model --------------------------------------------------------------------------
def test_new_columns_exist_and_serialise(app):
    with app.app_context():
        columns = {c.name for c in Place.__table__.columns}
        assert NEW_COLUMNS <= columns
        place = Place(name="Test Venue", category="Nightlife", subcategory="live_music", region="Durban",
                      latitude=-29.8, longitude=31.0, tags="live, outdoor ,", min_age=18, open_late=True)
        db.session.add(place)
        db.session.commit()
        data = place.to_dict()
        assert data["subcategory_label"] == "Live music"
        assert data["tags"] == ["live", "outdoor"]
        assert (data["min_age"], data["open_late"], data["open_evening"]) == (18, True, None)
        assert data["website"] is None and data["phone"] is None
        assert data["safety_rated"] is False and data["safety_score"] is None


def test_new_places_have_null_safety_not_neutral_default(app):
    with app.app_context():
        place = Place(name="Unrated", category="Food", latitude=0, longitude=0)
        db.session.add(place)
        db.session.commit()
        assert place.safety_score is None and place.to_dict()["safety_rated"] is False


def test_curated_places_keep_their_existing_safety_values(app):
    with app.app_context():
        rated = Place.query.filter(Place.safety_score.isnot(None)).count()
        assert rated == Place.query.filter_by(source="curated").count() > 0


# ---- migration: old database, nothing lost --------------------------------------------
OLD_SCHEMA = """
CREATE TABLE places (
    id INTEGER PRIMARY KEY, name VARCHAR(150) NOT NULL, description TEXT, category VARCHAR(50),
    address VARCHAR(200), opening_hours VARCHAR(100), image_url VARCHAR(500),
    latitude FLOAT NOT NULL, longitude FLOAT NOT NULL, is_indoor BOOLEAN, has_generator BOOLEAN,
    safety_score FLOAT, price_tier VARCHAR(10), source VARCHAR(20), last_updated DATETIME
);
CREATE TABLE clan_corrections (
    id INTEGER PRIMARY KEY, surname VARCHAR(100) NOT NULL, message TEXT NOT NULL,
    contact VARCHAR(120), created_at DATETIME
);
"""


@pytest.fixture
def old_db(tmp_path):
    """A database in the schema from before this phase, with data we must not lose."""
    con = sqlite3.connect(tmp_path / "test.db")
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO places (id, name, category, latitude, longitude, safety_score, price_tier, source, is_indoor, has_generator)"
                " VALUES (1, 'Curated One', 'Beach', -29.8, 31.0, 4.5, NULL, 'curated', 0, 0)")
    con.execute("INSERT INTO places (id, name, category, latitude, longitude, safety_score, price_tier, source, is_indoor, has_generator)"
                " VALUES (2, 'From OSM', 'Culture', -29.9, 31.1, 3.0, '$$', 'osm', 1, 0)")
    con.execute("INSERT INTO places (id, name, category, latitude, longitude, safety_score, price_tier, source, is_indoor, has_generator)"
                " VALUES (3, 'OSM Rated By Hand', 'Culture', -29.9, 31.2, 4.0, NULL, 'osm', 1, 0)")
    con.execute("INSERT INTO clan_corrections (id, surname, message) VALUES (1, 'Ndlovu', 'keep me')")
    con.commit()
    con.close()
    return tmp_path


def columns_of(path, table):
    con = sqlite3.connect(path / "test.db")
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    con.close()
    return cols


def test_migration_adds_columns_without_losing_data(old_db, data_dir):
    assert not NEW_COLUMNS & columns_of(old_db, "places")
    app = make_app(old_db, data_dir)
    try:
        assert NEW_COLUMNS <= columns_of(old_db, "places")
        with app.app_context():
            names = {p.name: p for p in Place.query.all()}
            assert set(names) == {"Curated One", "From OSM", "OSM Rated By Hand"}      # nothing deleted or re-seeded
            assert names["Curated One"].safety_score == 4.5                              # curated value kept
            assert names["From OSM"].safety_score is None                                # placeholder 3.0 cleared
            assert names["OSM Rated By Hand"].safety_score == 4.0                        # real OSM-sourced values kept
            assert names["From OSM"].price_tier is None                                  # Phase 1 placeholder cleared
            assert names["Curated One"].region is None and names["Curated One"].min_age is None
            from app.models import ClanCorrection
            assert ClanCorrection.query.one().message == "keep me"                       # other tables untouched
            assert SchemaMigration.query.count() >= 3
    finally:
        with app.app_context():
            db.engine.dispose()


def test_migration_is_safe_to_run_again(old_db, data_dir):
    first = make_app(old_db, data_dir)
    with first.app_context():
        db.engine.dispose()
    second = make_app(old_db, data_dir)            # a second start must not fail or duplicate anything
    try:
        with second.app_context():
            assert Place.query.count() == 3
            assert len({m.key for m in SchemaMigration.query.all()}) == SchemaMigration.query.count()
    finally:
        with second.app_context():
            db.engine.dispose()


def test_migration_works_when_columns_already_exist(app):
    from app.migrations import _add_place_columns
    with app.app_context():
        _add_place_columns()                       # fresh DB already has them: must be a no-op
        assert NEW_COLUMNS <= {c["name"] for c in db.inspect(db.engine).get_columns("places")}


# ---- recommender: NULL safety = not rated ------------------------------------------------
def fake(safety, name="X"):
    return SimpleNamespace(
        id=1, name=name, is_indoor=True, has_generator=False, safety_score=safety, category="Culture",
        latitude=0, longitude=0, to_dict=lambda: {"name": name, "category": "Culture", "safety_score": safety})


CALM = {"weather": describe_weather(1, 22), "loadshedding": False}


def rank(safety, prefs=None):
    return recommend_places([fake(safety)], prefs or {}, CALM)[0]


def test_null_safety_gets_no_points_and_no_chip():
    unrated, neutral = rank(None), rank(3.0)
    assert unrated["score"] == neutral["score"]                     # not a penalty, not a bonus
    assert not any("safety" in r["text"].lower() for r in unrated["reasons"])


def test_rated_places_still_score_and_say_it_is_a_curator_rating():
    high, low = rank(5.0), rank(1.0)
    assert high["score"] > rank(None)["score"] > low["score"]
    texts = [r["text"] for r in high["reasons"]]
    assert "Curator safety rating 5/5" in texts


def test_min_safety_never_penalises_unrated_places():
    assert rank(None, {"min_safety": 4.0})["score"] == rank(None)["score"]
    below = rank(3.5, {"min_safety": 4.0})
    assert below["score"] < rank(3.5)["score"]
    assert any("below your minimum" in r["text"] for r in below["reasons"])


def test_no_verdict_words_in_safety_chips():
    for value in (None, 1.0, 3.0, 4.6, 5.0):
        for r in rank(value, {"min_safety": 4.0})["reasons"]:
            assert " unsafe" not in r["text"].lower() and "highly rated for safety" not in r["text"].lower()
            assert " is safe" not in r["text"].lower()


# ---- ETL no longer invents safety -----------------------------------------------------------
def test_etl_leaves_safety_null():
    rows = pipeline.transform([{"type": "node", "id": 1, "lat": -29.8, "lon": 31.0, "tags": {"name": "Test Museum", "tourism": "museum"}}])
    assert rows[0]["safety_score"] is None and rows[0]["price_tier"] is None


# ---- overrides understand the new fields ---------------------------------------------------------
def override(app, tmp_path, fields):
    with app.app_context():
        name = Place.query.order_by(Place.id).first().name
        path = tmp_path / "o.json"
        path.write_text(json.dumps({name: fields}), encoding="utf-8")
        warnings = apply_overrides(path)
        return warnings, db.session.get(Place, Place.query.filter_by(name=name).one().id)


def test_overrides_set_new_fields(app, tmp_path):
    warnings, place = override(app, tmp_path, {
        "subcategory": "cinema", "region": "Durban", "website": "https://example.org/x", "phone": "+27 31 000 0000",
        "min_age": 0, "open_evening": True, "open_late": False, "tags": "indoor, family", "opening_hours_raw": "Mo-Su 10:00-22:00"})
    assert warnings == []
    assert (place.subcategory, place.region, place.min_age, place.open_evening, place.open_late) == ("cinema", "Durban", 0, True, False)
    assert place.website == "https://example.org/x" and place.tags == "indoor, family"


@pytest.mark.parametrize("fields", [
    {"subcategory": "strip_club"}, {"region": "Atlantis"}, {"website": "javascript:alert(1)"},
    {"phone": "call me"}, {"min_age": -1}, {"min_age": 18.5}, {"open_late": "yes"}, {"safety_score": True},
])
def test_invalid_new_field_values_are_rejected(app, tmp_path, fields):
    warnings, place = override(app, tmp_path, fields)
    assert len(warnings) == 1
    assert all(getattr(place, key) in (None, place.safety_score) for key in fields if key != "safety_score")
