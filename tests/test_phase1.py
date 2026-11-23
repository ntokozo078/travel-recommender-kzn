"""Phase 1: SAST clock, 'simulated' labels, real price tiers (migration, overrides, filter)."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import db
from app.migrations import MIGRATIONS, run_migrations
from app.models import Place, SchemaMigration
from app.overrides import apply_overrides
from app.services import ContextEngine, SAST
from etl_pipeline import pipeline
from ml_engine.recommender import recommend_places
from ml_engine.weather_rules import describe_weather

UTC = timezone.utc


# ---- load-shedding clock (South African time, not the server's) --------
@pytest.mark.parametrize("utc_hour, utc_minute, expected", [
    (15, 59, False),    # 17:59 SAST
    (16, 0, True),      # 18:00 SAST
    (18, 59, True),     # 20:59 SAST
    (19, 0, False),     # 21:00 SAST
    (3, 0, False),      # 05:00 SAST
])
def test_loadshedding_follows_south_african_time(utc_hour, utc_minute, expected):
    engine = ContextEngine(clock=lambda: datetime(2026, 11, 23, utc_hour, utc_minute, tzinfo=UTC))
    assert engine.check_loadshedding("auto") is expected


def test_server_in_utc_would_have_been_wrong():
    # 18:30 UTC is 20:30 SAST (evening); 19:30 UTC is 21:30 SAST. A UTC-based check gets both wrong.
    assert ContextEngine(clock=lambda: datetime(2026, 11, 23, 18, 30, tzinfo=UTC)).check_loadshedding() is True
    assert ContextEngine(clock=lambda: datetime(2026, 11, 23, 19, 30, tzinfo=UTC)).check_loadshedding() is False


def test_clock_in_other_zones_is_converted():
    other = timezone(timedelta(hours=-5))        # 11:00 at UTC-5 is 18:00 SAST
    assert ContextEngine(clock=lambda: datetime(2026, 11, 23, 11, 0, tzinfo=other)).check_loadshedding() is True


def test_manual_modes_ignore_the_clock():
    engine = ContextEngine(clock=lambda: datetime(2026, 11, 23, 3, 0, tzinfo=UTC))
    assert engine.check_loadshedding("on") is True
    assert engine.check_loadshedding("off") is False


def test_default_clock_is_sast_aware():
    assert ContextEngine().clock().utcoffset() == SAST.utcoffset(None) or ContextEngine().clock().utcoffset() == timedelta(hours=2)


# ---- "simulated" is stated wherever power affects the result ----------
def test_power_reasons_say_simulated():
    place = lambda gen: SimpleNamespace(
        id=1, name="X", is_indoor=True, has_generator=gen, safety_score=4.0, category="Culture",
        latitude=0, longitude=0, to_dict=lambda: {"name": "X", "category": "Culture"})
    context = {"weather": describe_weather(1, 22), "loadshedding": True, "loadshedding_simulated": True}
    with_gen = recommend_places([place(True)], {}, context)[0]["reasons"]
    without = recommend_places([place(False)], {}, context)[0]["reasons"]
    texts = [r["text"] for r in with_gen + without if "load-shedding" in r["text"].lower()]
    assert len(texts) == 2 and all("(simulated)" in t for t in texts)


def test_context_api_flags_simulated(client, monkeypatch):
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 22))
    assert client.get("/api/context").get_json()["loadshedding_simulated"] is True


# ---- price tiers are real data or NULL --------------------------------
@pytest.fixture
def fake_weather(monkeypatch):
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 22))


def set_prices(app, mapping):
    with app.app_context():
        for name, tier in mapping.items():
            Place.query.filter_by(name=name).one().price_tier = tier
        db.session.commit()
        return [p.name for p in Place.query.order_by(Place.name).limit(6)]


def test_fresh_database_has_no_placeholder_prices(app):
    with app.app_context():
        assert Place.query.count() > 0
        assert Place.query.filter(Place.price_tier.isnot(None)).count() == 0


def test_filters_endpoint_only_counts_known_prices(app, client):
    assert client.get("/api/filters").get_json()["prices"] == {"$": 0, "$$": 0, "$$$": 0}
    names = set_prices(app, {})
    set_prices(app, {names[0]: "$", names[1]: "$$", names[2]: "$$"})
    assert client.get("/api/filters").get_json()["prices"] == {"$": 1, "$$": 2, "$$$": 0}


def test_price_filter_is_up_to_and_excludes_unknown(app, client, fake_weather):
    names = set_prices(app, {})
    set_prices(app, {names[0]: "$", names[1]: "$$", names[2]: "$$$"})

    def found(query):
        data = client.get(f"/api/recommend?limit=50&{query}").get_json()
        return {r["name"]: r["price_tier"] for r in data["results"]}

    assert found("price=1") == {names[0]: "$"}
    assert found("price=%24%24") == {names[0]: "$", names[1]: "$$"}          # "$$"
    assert set(found("price=3").values()) == {"$", "$$", "$$$"}               # unknown-price places excluded
    assert len(found("")) > 3                                                  # no filter: everything
    assert len(found("price=any")) == len(found(""))


def test_invalid_price_is_a_400(client, fake_weather):
    for bad in ("cheap", "4", "$$$$", "0"):
        assert client.get(f"/api/recommend?price={bad}").status_code == 400


def test_cards_expose_price_or_null(app, client, fake_weather):
    names = set_prices(app, {})
    set_prices(app, {names[0]: "$$"})
    prices = {r["name"]: r["price_tier"] for r in client.get("/api/recommend?limit=50").get_json()["results"]}
    assert prices[names[0]] == "$$" and prices[names[1]] is None


def test_etl_no_longer_invents_a_price():
    rows = pipeline.transform([{"type": "node", "id": 1, "lat": -29.8, "lon": 31.0, "tags": {"name": "Test Museum", "tourism": "museum"}}])
    assert rows and rows[0]["price_tier"] is None


# ---- migration -------------------------------------------------------------
def test_migration_clears_placeholder_once_and_never_again(app):
    with app.app_context():
        SchemaMigration.query.delete()
        first = Place.query.order_by(Place.id).first()
        first.price_tier = "$$"
        db.session.commit()

        run_migrations()
        assert db.session.get(Place, first.id).price_tier is None
        assert SchemaMigration.query.count() == len(MIGRATIONS)

        first.price_tier = "$$"                  # a real value set later must survive restarts
        db.session.commit()
        run_migrations()
        assert db.session.get(Place, first.id).price_tier == "$$"


def test_migration_never_deletes_rows(app):
    with app.app_context():
        before = Place.query.count()
        SchemaMigration.query.delete()
        db.session.commit()
        run_migrations()
        assert Place.query.count() == before


# ---- overrides file -----------------------------------------------------------
def write(tmp_path, data):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_overrides_apply_and_are_idempotent(app, tmp_path):
    with app.app_context():
        name = Place.query.order_by(Place.id).first().name
        path = write(tmp_path, {"_format": "x", name.upper(): {"price_tier": "$$$", "safety_score": 4.2, "opening_hours": "08:00 - 17:00"}})
        assert apply_overrides(path) == []
        assert apply_overrides(path) == []
        place = Place.query.filter_by(name=name).one()
        assert (place.price_tier, place.safety_score, place.opening_hours) == ("$$$", 4.2, "08:00 - 17:00")


def test_override_null_clears_a_value(app, tmp_path):
    with app.app_context():
        name = Place.query.order_by(Place.id).first().name
        apply_overrides(write(tmp_path, {name: {"price_tier": "$"}}))
        apply_overrides(write(tmp_path, {name: {"price_tier": None}}))
        assert Place.query.filter_by(name=name).one().price_tier is None


def test_bad_overrides_warn_and_are_ignored(app, tmp_path):
    with app.app_context():
        name = Place.query.order_by(Place.id).first().name
        original = Place.query.filter_by(name=name).one().safety_score
        warnings = apply_overrides(write(tmp_path, {
            name: {"price_tier": "$$$$", "safety_score": 9, "bogus": 1},
            "No Such Place": {"price_tier": "$"},
        }))
        place = Place.query.filter_by(name=name).one()
        assert place.price_tier is None and place.safety_score == original
        assert any("No such" in w or "no place" in w for w in warnings)
        assert any("bogus" in w for w in warnings)


def test_unreadable_overrides_file_does_not_crash(app, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{nope", encoding="utf-8")
    with app.app_context():
        assert apply_overrides(path)            # returns a warning
        assert apply_overrides(tmp_path / "missing.json") == []


def test_shipped_overrides_file_is_valid(app):
    from tests.conftest import ROOT
    with app.app_context():
        assert apply_overrides(ROOT / "data" / "place_overrides.json") == []
