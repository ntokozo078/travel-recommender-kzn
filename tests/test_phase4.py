"""Phase 4: time of day, opening hours, safety weighting, vibes, tourist mode, explainable scores."""
import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import db
from app.models import Place
from app.services import ContextEngine
from etl_pipeline.osm_mapping import is_open_at
from ml_engine.recommender import category_cap, diversify, recommend_places, score_place
from ml_engine.weather_rules import describe_weather

UTC = timezone.utc
WED = 2


def place(**kw):
    values = dict(id=1, name="P", category="Culture", subcategory=None, is_indoor=False, has_generator=False,
                  safety_score=None, latitude=-29.85, longitude=31.02, price_tier=None, opening_hours=None,
                  opening_hours_raw=None, open_evening=None, open_late=None, min_age=None)
    values.update(kw)
    ns = SimpleNamespace(**values)
    ns.to_dict = lambda: {"name": ns.name, "category": ns.category}
    return ns


def ctx(weather=(1, 22), evening=False, minutes=None, weekday=WED, loadshedding=False, with_time=True):
    minutes = (20 * 60 if evening else 12 * 60) if minutes is None else minutes
    out = {"weather": describe_weather(*weather), "loadshedding": loadshedding}
    if with_time:
        out["time"] = {"minutes": minutes, "weekday": weekday, "evening": evening, "what_if": False}
    return out


def score(p, context, **prefs):
    return score_place(p, context, prefs)[0]


def chips(p, context, **prefs):
    return {r["text"]: r["points"] for r in score_place(p, context, prefs)[1]}


# ---- wet / dry -----------------------------------------------------------------------
def test_wet_weather_favours_indoor_places_any_time_of_day():
    for evening in (False, True):
        wet = ctx(weather=(63, 18), evening=evening)
        assert chips(place(is_indoor=True), wet)["Indoors, so you stay dry"] == 5
        assert chips(place(is_indoor=False), wet)["Outdoors, so it may be wet"] == -3


def test_dry_day_rewards_outdoor_places_but_dry_evening_does_not():
    assert chips(place(), ctx())["Great weather to be outside"] == 3
    assert chips(place(is_indoor=True), ctx()) == {}
    assert "Great weather to be outside" not in chips(place(), ctx(evening=True))      # the sun has set


def test_hot_day_beach_bonus_is_daytime_only():
    hot = (0, 34)
    assert chips(place(category="Beach"), ctx(weather=hot))["Hot day, perfect for the water"] == 4
    assert "Hot day, perfect for the water" not in chips(place(category="Beach"), ctx(weather=hot, evening=True))


def test_loadshedding_chips_carry_points_and_say_simulated():
    on = ctx(loadshedding=True)
    assert chips(place(has_generator=True), on)["Backup generator during load-shedding (simulated)"] == 5
    assert chips(place(), on)["May be affected by load-shedding (simulated)"] == -5


# ---- when does evening start ------------------------------------------------------------
@pytest.mark.parametrize("utc_h, utc_m, evening", [
    (15, 29, False),    # 17:29 SAST
    (15, 30, True),     # 17:30 SAST
    (21, 59, True),     # 23:59 SAST
    (0, 0, True),       # 02:00 SAST, still a night out
    (1, 59, True),      # 03:59 SAST
    (2, 0, False),      # 04:00 SAST
    (10, 0, False),     # noon SAST
])
def test_evening_starts_at_1730_south_african_time(utc_h, utc_m, evening):
    engine = ContextEngine(clock=lambda: datetime(2026, 11, 23, utc_h, utc_m, tzinfo=UTC))
    assert engine.time_context()["evening"] is evening


def test_what_if_time_overrides_the_clock_and_drives_load_shedding():
    engine = ContextEngine(clock=lambda: datetime(2026, 11, 23, 8, 0, tzinfo=UTC))        # 10:00 SAST Monday
    now = engine.time_context()
    assert (now["time"], now["weekday"], now["what_if"]) == ("10:00", 0, False)
    night = engine.time_context("21:30")
    assert (night["time"], night["evening"], night["what_if"], night["weekday"]) == ("21:30", True, True, 0)
    assert engine.get_context(-29.8, 31.0, "auto", at="19:00")["loadshedding"] is True       # 19:00 is in the simulated window
    assert engine.get_context(-29.8, 31.0, "auto", at="12:00")["loadshedding"] is False


# ---- evening vs day -------------------------------------------------------------------------
def test_nightlife_is_boosted_after_dark_and_held_back_in_the_day():
    club = place(category="Nightlife", subcategory="nightclub", is_indoor=True)
    assert chips(club, ctx(evening=True))["Nightlife is at its best after dark"] == 6
    assert chips(club, ctx())["More of an evening venue"] == -4
    assert score(club, ctx(evening=True)) > score(club, ctx())


def test_a_nightlife_venue_listed_as_open_by_day_is_not_held_back():
    taproom = place(category="Nightlife", opening_hours_raw="Mo-Su 11:00-22:00", is_indoor=True)
    assert "More of an evening venue" not in chips(taproom, ctx())
    assert chips(taproom, ctx())["Open now (per listed hours)"] == 2


def test_daylight_categories_are_ranked_lower_in_the_evening():
    for category in ("Beach", "Nature", "Adventure"):
        assert chips(place(category=category), ctx(evening=True))["Best in daylight"] == -4
        assert "Best in daylight" not in chips(place(category=category), ctx())


def test_evening_entertainment_uses_listed_hours_first_then_type():
    listed = place(category="Entertainment", subcategory="arcade", open_evening=True, is_indoor=True)
    assert chips(listed, ctx(evening=True))["Open in the evening (per listed hours)"] == 4
    typical = place(category="Entertainment", subcategory="cinema", is_indoor=True)
    assert chips(typical, ctx(evening=True))["Usually an evening venue (hours not listed)"] == 2
    unknown = place(category="Entertainment", subcategory="mini_golf")
    assert not any("evening" in t for t in chips(unknown, ctx(evening=True)))                # no hours, no assumption
    day_only = place(category="Entertainment", subcategory="cinema", open_evening=False, is_indoor=True)
    assert "Usually an evening venue (hours not listed)" not in chips(day_only, ctx(evening=True))


def test_places_closed_at_this_time_are_demoted():
    mall = place(category="Shopping", opening_hours="09:00 - 19:00", is_indoor=True)
    assert chips(mall, ctx(minutes=12 * 60))["Open now (per listed hours)"] == 2
    assert chips(mall, ctx(evening=True, minutes=20 * 60))["Closed right now (per listed hours)"] == -6
    assert score(mall, ctx(evening=True, minutes=20 * 60)) < score(mall, ctx(minutes=12 * 60))


def test_day_only_flag_demotes_when_the_text_cannot_be_evaluated():
    odd = place(category="Food", opening_hours_raw="sunrise-sunset", open_evening=False)
    assert chips(odd, ctx(evening=True))["Listed hours end before the evening"] == -5
    assert "Listed hours end before the evening" not in chips(odd, ctx())                    # only an evening rule


def test_unknown_hours_never_change_the_score():
    assert chips(place(category="Culture", is_indoor=True), ctx(evening=True)) == {}
    assert chips(place(category="Culture", is_indoor=True, opening_hours="by appointment"), ctx(evening=True)) == {}


def test_without_a_time_context_no_time_rules_apply():
    club = place(category="Nightlife", opening_hours_raw="Mo-Su 18:00-23:00")
    assert not any("evening" in t.lower() or "open now" in t.lower() or "closed" in t.lower()
                   for t in chips(club, ctx(with_time=False)))


# ---- opening hours engine ----------------------------------------------------------------------
@pytest.mark.parametrize("raw, weekday, minute, expected", [
    ("Mo-Fr 09:00-17:00", 0, 12 * 60, True),
    ("Mo-Fr 09:00-17:00", 0, 18 * 60, False),
    ("Mo-Fr 09:00-17:00", 5, 12 * 60, False),                      # Saturday not listed = closed
    ("Mo-Fr 09:00-17:00; Sa 09:00-13:00", 5, 12 * 60, True),
    ("Mo-Fr 17:00-02:00", 4, 23 * 60, True),                      # Friday night
    ("Mo-Fr 17:00-02:00", 5, 60, True),                           # ...still open at 01:00 Saturday
    ("Mo-Fr 17:00-02:00", 5, 3 * 60, False),
    ("Mo-Fr 17:00-02:00", 0, 60, False),                          # Sunday night was not listed, so Monday 01:00 is closed
    ("Mo-Su 10:00-22:00; Su off", 6, 12 * 60, False),             # later rule overrides
    ("Mo-Su 09:00-17:00; PH off", 2, 10 * 60, True),              # public-holiday rules are ignored
    ("Mo-Su 11:00-14:00,18:00-22:00", 1, 19 * 60, True),
    ("Mo-Su 11:00-14:00,18:00-22:00", 1, 16 * 60, False),
    ("Sa-Mo 10:00-16:00", 0, 12 * 60, True),                      # wrap-around day range
    ("Sa-Mo 10:00-16:00", 2, 12 * 60, False),
    ("24/7", 3, 3 * 60, True),
    ("24 Hours", 3, 3 * 60, True),
    ("09:00 - 17:00", 6, 10 * 60, True),                          # curated style, every day
    ("sunrise-sunset", 1, 12 * 60, None),
    ("by appointment", 1, 12 * 60, None),
    ("", 1, 12 * 60, None),
    (None, 1, 12 * 60, None),
])
def test_is_open_at(raw, weekday, minute, expected):
    assert is_open_at(raw, weekday, minute) is expected


def test_is_open_at_only_proves_open_when_part_of_the_text_is_unclear():
    assert is_open_at("Mo-Fr 09:00-17:00; Sa sunset-late", 1, 12 * 60) is True
    assert is_open_at("Mo-Fr 09:00-17:00; Sa sunset-late", 1, 20 * 60) is None


# ---- safety: only for places that have a rating ---------------------------------------------------
def test_null_safety_is_not_rated_and_never_changes_the_score_by_time():
    unrated = place(category="Culture", is_indoor=True)
    assert score(unrated, ctx()) == score(unrated, ctx(evening=True)) == 0
    assert not any("safety" in t.lower() for t in chips(unrated, ctx(evening=True)))


def test_safety_counts_more_in_the_evening_but_only_when_rated():
    rated = place(category="Culture", is_indoor=True, safety_score=5.0)
    assert chips(rated, ctx())["Curator safety rating 5/5"] == 4.0
    evening = chips(rated, ctx(evening=True))
    assert evening["Curator safety rating 5/5 (counts for more in the evening)"] == 6.0
    low = place(category="Culture", is_indoor=True, safety_score=1.0)
    assert chips(low, ctx(evening=True))["Curator safety rating 1/5 (counts for more in the evening)"] == -6.0
    assert score(rated, ctx(evening=True)) > score(place(category="Culture", is_indoor=True), ctx(evening=True)) > score(low, ctx(evening=True))


def test_min_safety_only_penalises_rated_places():
    unrated = place(category="Culture", is_indoor=True)
    assert score(unrated, ctx(), min_safety=4.5) == 0
    rated = place(category="Culture", is_indoor=True, safety_score=3.5)       # +1 for the rating, -4 for being under the minimum
    assert score(rated, ctx(), min_safety=4.5) == -3.0


# ---- vibes ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("vibe, winner, loser", [
    ("nightlife", place(category="Nightlife"), place(category="Nature")),
    ("nature", place(category="Nature"), place(category="Shopping", is_indoor=True)),
    ("culture", place(category="Culture"), place(category="Shopping", is_indoor=True)),
    ("food", place(category="Food"), place(category="Shopping", is_indoor=True)),
    ("family", place(category="Entertainment", subcategory="water_park"), place(category="Nightlife", subcategory="nightclub")),
])
def test_vibes_lift_matching_places(vibe, winner, loser):
    assert score(winner, ctx(), vibes=[vibe]) - score(winner, ctx()) > score(loser, ctx(), vibes=[vibe]) - score(loser, ctx())


def test_family_vibe_flags_adult_venues_but_not_ones_with_a_known_low_age():
    club = place(category="Nightlife", subcategory="bar")
    assert chips(club, ctx(), vibes=["family"])["Often 18+, so check age rules"] == -6
    assert "Often 18+, so check age rules" not in chips(place(category="Nightlife", min_age=0), ctx(), vibes=["family"])
    assert chips(place(category="Entertainment", subcategory="casino"), ctx(), vibes=["family"])["Often 18+, so check age rules"] == -6


def test_budget_vibe_only_uses_known_prices():
    assert chips(place(price_tier="$"), ctx(), vibes=["budget"])["Budget-friendly ($)"] == 5
    assert chips(place(price_tier="$$$"), ctx(), vibes=["budget"])["Higher price ($$$)"] == -3
    assert not any("$" in t for t in chips(place(price_tier=None), ctx(), vibes=["budget"]))     # unknown price: no guess


def test_several_vibes_add_up():
    both = place(category="Nature")
    assert score(both, ctx(), vibes=["nature", "family"]) == score(both, ctx()) + 6 + 3


# ---- every point change has a chip ----------------------------------------------------------------------
CATEGORIES = [("Beach", None), ("Nature", None), ("Culture", None), ("Shopping", None),
              ("Nightlife", "bar"), ("Entertainment", "cinema"), ("Entertainment", "arcade")]


@pytest.mark.parametrize("category_sub, evening, weather, power, safety, vibes", list(itertools.product(
    CATEGORIES, (False, True), [(1, 22), (63, 15), (0, 35), (3, 5)], (False, True), (None, 0.5, 3.2, 4.8),
    ([], ["nightlife", "budget"], ["family", "food"]))))
def test_score_is_exactly_the_sum_of_the_chip_points(category_sub, evening, weather, power, safety, vibes):
    category, sub = category_sub
    p = place(category=category, subcategory=sub, safety_score=safety, price_tier="$$", opening_hours="09:00 - 22:00", is_indoor=bool(sub))
    context = ctx(weather=weather, evening=evening, loadshedding=power)
    total, reasons, _ = score_place(p, context, {"min_safety": 4.0, "vibes": vibes, "lat": -29.9, "lon": 31.1})
    assert total == round(sum(r["points"] for r in reasons), 1)
    assert all(set(r) == {"text", "tone", "points"} for r in reasons)


# ---- tourist mode ---------------------------------------------------------------------------------------------
def ranked(*categories):
    return [{"name": f"{c}{i}", "category": c} for i, c in enumerate(categories)]


def test_category_cap_scales_with_the_list_size():
    assert [category_cap(n) for n in (1, 3, 4, 5, 8, 12, 24)] == [1, 1, 1, 2, 2, 3, 6]


def test_diversify_caps_each_category_and_keeps_best_first_order():
    items = ranked("Shopping", "Shopping", "Shopping", "Shopping", "Food", "Beach", "Shopping", "Culture", "Nature", "Nightlife")
    top = diversify(items, 6, cap=2)
    assert [i["name"] for i in top] == ["Shopping0", "Shopping1", "Food4", "Beach5", "Culture7", "Nature8"]
    assert max(sum(1 for i in top if i["category"] == c) for c in {i["category"] for i in top}) <= 2


def test_diversify_still_fills_the_list_when_there_are_too_few_categories():
    items = ranked("Shopping", "Shopping", "Shopping", "Shopping", "Food")
    top = diversify(items, 4, cap=1)
    assert len(top) == 4 and [i["name"] for i in top][:2] == ["Shopping0", "Food4"]


def test_diversify_with_default_cap():
    items = ranked(*["Shopping"] * 10, *["Food"] * 10, *["Nature"] * 10)
    top = diversify(items, 12)
    assert len(top) == 12
    first_nine = top[:9]                                    # three categories x cap 3, then the best leftovers
    assert all(sum(1 for i in first_nine if i["category"] == c) == 3 for c in ("Shopping", "Food", "Nature"))


# ---- API -----------------------------------------------------------------------------------------------------------
@pytest.fixture
def fake_weather(monkeypatch):
    monkeypatch.setattr(ContextEngine, "get_current_weather", lambda self, lat, lon: describe_weather(1, 22))


def test_api_returns_time_context_and_what_if(client, fake_weather):
    data = client.get("/api/recommend?at=21:30&limit=3").get_json()
    when = data["context"]["time"]
    assert (when["time"], when["evening"], when["what_if"]) == ("21:30", True, True)
    assert all("points" in r for place_ in data["results"] for r in place_["reasons"])
    assert client.get("/api/context?at=09:00").get_json()["time"]["evening"] is False
    assert client.get("/api/context?at=23:00").get_json()["time"]["evening"] is True


def test_api_rejects_bad_time_and_vibe(client, fake_weather):
    for bad in ("25:00", "9pm", "12:60", "noon"):
        assert client.get(f"/api/recommend?at={bad}").status_code == 400, bad
    assert client.get("/api/recommend?vibe=party").status_code == 400
    assert client.get("/api/recommend?vibe=food,nature,culture,family").status_code == 400      # at most 3
    assert client.get("/api/recommend?vibe=Food,NATURE").status_code == 200


def test_api_vibe_changes_the_ranking(client, fake_weather):
    plain = [r["name"] for r in client.get("/api/recommend?limit=50").get_json()["results"]]
    nature = client.get("/api/recommend?limit=50&vibe=nature").get_json()
    assert nature["vibes"] == ["nature"]
    assert nature["results"][0]["category"] == "Nature" and plain != [r["name"] for r in nature["results"]]


def test_api_evening_puts_nightlife_first_and_closed_places_last(app, client, fake_weather):
    with app.app_context():
        db.session.add(Place(name="Test Club", category="Nightlife", subcategory="nightclub", latitude=-29.8, longitude=31.0,
                             is_indoor=True, opening_hours_raw="Mo-Su 20:00-04:00", open_evening=True, open_late=True))
        db.session.commit()
    evening = client.get("/api/recommend?at=22:00&limit=50").get_json()["results"]
    assert evening[0]["name"] == "Test Club"
    day = client.get("/api/recommend?at=11:00&limit=50").get_json()["results"]
    assert [r["name"] for r in day].index("Test Club") > 5                          # held back before opening time
    closed = {r["name"] for r in evening if any("Closed right now" in c["text"] for c in r["reasons"])}
    assert closed and evening[-1]["name"] in closed


def test_api_tourist_mode_caps_each_category(app, client, fake_weather):
    with app.app_context():
        for i in range(15):                                   # a mall-heavy dataset
            db.session.add(Place(name=f"Mall {i}", category="Shopping", latitude=-29.8 - i / 1000, longitude=31.0,
                                 is_indoor=True, has_generator=True, safety_score=5.0, opening_hours="24/7"))
        db.session.commit()
    plain = client.get("/api/recommend?limit=12&at=20:00&loadshedding=on").get_json()          # generators win during an outage
    assert sum(r["category"] == "Shopping" for r in plain["results"]) > 3             # without the mode malls take over
    assert plain["tourist_mode"] == {"enabled": False, "cap_per_category": None}

    mixed = client.get("/api/recommend?limit=12&at=20:00&loadshedding=on&tourist=1").get_json()
    counts = {}
    for r in mixed["results"]:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    assert len(mixed["results"]) == 12 and max(counts.values()) <= 3 and len(counts) >= 4
    assert mixed["tourist_mode"] == {"enabled": True, "cap_per_category": 3}


def test_tourist_mode_is_ignored_when_a_category_is_chosen(client, fake_weather):
    data = client.get("/api/recommend?category=Shopping&limit=4&tourist=1").get_json()
    assert data["tourist_mode"]["enabled"] is False and len(data["results"]) == 4 and {r["category"] for r in data["results"]} == {"Shopping"}
