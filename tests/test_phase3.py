"""Phase 3: province-wide OSM ETL, tested offline from fixture data (no network)."""
import json
import sqlite3
from types import SimpleNamespace

import pytest
import requests

from app import db
from app.models import Place
from etl_pipeline import osm_mapping as om
from etl_pipeline import overpass, pipeline, regions
from etl_pipeline.loader import load_rows
from etl_pipeline.overpass import OverpassError
from tests.conftest import ROOT, make_app


def el(osm_id, name, lat=-29.85, lon=31.02, kind="node", region="Durban", **tags):
    tags = dict(tags, **({"name": name} if name else {}))
    out = {"type": kind, "id": osm_id, "tags": tags, "_region": region}
    if kind == "node":
        out.update(lat=lat, lon=lon)
    else:
        out["center"] = {"lat": lat, "lon": lon}
    return out


# ---- tag mapping (every tag you asked for) ----------------------------------------------
@pytest.mark.parametrize("tags, expected", [
    ({"amenity": "nightclub"}, ("Nightlife", "nightclub")),
    ({"amenity": "bar"}, ("Nightlife", "bar")),
    ({"amenity": "pub"}, ("Nightlife", "pub")),
    ({"amenity": "biergarten"}, ("Nightlife", "pub")),
    ({"amenity": "cinema"}, ("Entertainment", "cinema")),
    ({"amenity": "theatre"}, ("Entertainment", "theatre")),
    ({"amenity": "casino"}, ("Entertainment", "casino")),
    ({"amenity": "events_venue"}, ("Entertainment", "events_venue")),
    ({"amenity": "arts_centre"}, ("Culture", None)),
    ({"leisure": "bowling_alley"}, ("Entertainment", "bowling")),
    ({"leisure": "ice_rink"}, ("Entertainment", "ice_skating")),
    ({"leisure": "amusement_arcade"}, ("Entertainment", "arcade")),
    ({"leisure": "miniature_golf"}, ("Entertainment", "mini_golf")),
    ({"leisure": "water_park"}, ("Entertainment", "water_park")),
    ({"leisure": "trampoline_park"}, ("Entertainment", None)),
    ({"leisure": "escape_game"}, ("Entertainment", None)),
    ({"leisure": "dance"}, ("Entertainment", None)),
    ({"tourism": "theme_park"}, ("Entertainment", "amusement_park")),
    ({"tourism": "zoo"}, ("Nature", None)),
    ({"tourism": "aquarium"}, ("Entertainment", None)),
    ({"tourism": "attraction", "name": "Some Statue"}, ("Entertainment", None)),
    ({"sport": "karting"}, ("Entertainment", "go_karting")),
    ({"sport": "motor_sport;karting"}, ("Entertainment", "go_karting")),
    ({"tourism": "museum"}, ("Culture", None)),          # kept from the first ETL
])
def test_classify_maps_requested_tags(tags, expected):
    category, sub, _indoor, _src = om.classify(tags)
    assert (category, sub) == expected


def test_every_requested_tag_value_is_in_the_query():
    query = overpass.build_query(regions.CHUNKS[0].area_id)
    for value in ("nightclub", "bar", "pub", "cinema", "theatre", "casino", "arts_centre", "events_venue",
                  "biergarten", "bowling_alley", "ice_rink", "amusement_arcade", "miniature_golf", "water_park",
                  "trampoline_park", "escape_game", "dance", "theme_park", "zoo", "aquarium", "attraction", "karting"):
        assert value in query, value
    assert '["name"]' in query                                   # unnamed features are not even downloaded
    assert f"area({3600000000 + 610736})" in query                # relation id + 3.6 billion
    assert "around" not in query                                  # boundary area, not a radius


@pytest.mark.parametrize("tags, sub", [
    ({"amenity": "bar", "name": "Mama's Shisa Nyama"}, "shisa_nyama"),
    ({"amenity": "bar", "name": "Sky Lounge"}, "lounge"),
    ({"amenity": "pub", "name": "Hops Taproom"}, "brewery_taproom"),
    ({"amenity": "bar", "name": "Plain Bar"}, "bar"),
    ({"amenity": "theatre", "name": "Comedy Cellar"}, "comedy"),
])
def test_name_hints_refine_subcategory(tags, sub):
    assert om.classify(tags)[1] == sub


def test_name_hints_never_change_the_category_of_venues():
    assert om.classify({"amenity": "bar", "name": "The Beach Bar"})[:2] == ("Nightlife", "bar")
    assert om.classify({"tourism": "attraction", "name": "Sunset Beach"})[0] == "Beach"     # only for vague tags


def test_lodging_we_do_not_want_and_unknown_tags_are_skipped():
    for tourism in ("apartment", "motel", "caravan_site", "alpine_hut"):
        assert om.classify({"tourism": tourism, "name": "X"}) is None
    assert om.classify({"amenity": "bench", "name": "X"}) is None
    assert om.classify({}) is None


# ---- opening hours ---------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("24/7", (True, True)),
    ("Mo-Su 17:00-02:00", (True, True)),             # past midnight
    ("Mo-Sa 18:00-23:00", (True, False)),            # evening, but closes at 23:00
    ("Mo-Fr 09:00-17:00; Sa 09:00-13:00", (False, False)),
    ("Mo-Su 10:00-24:00", (True, True)),
    ("Mo-Th 09:00-17:00; Fr-Sa 09:00-23:30; Su off", (True, True)),
    ("Mo-Fr 09:00-17:00; PH off", (False, False)),
    ("Mo-Su 19:00-22:00", (True, False)),
    ("Mo-Su 11:00,18:00-22:00", (None, None)),       # not understood: unknown
    ("sunrise-sunset", (None, None)),
    ("by appointment", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_parse_opening_hours(raw, expected):
    assert om.parse_opening_hours(raw) == expected


def test_partly_understood_hours_only_prove_true():
    # One rule is gibberish, but the other proves the venue is open in the evening.
    assert om.parse_opening_hours("Mo-Fr 18:00-22:00; Sa sunset-late") == (True, None)
    assert om.parse_opening_hours("Mo-Fr 08:00-12:00; Sa sunset-late") == (None, None)


# ---- contact fields -------------------------------------------------------------------------
def test_contact_cleaning():
    assert om.clean_website({"website": "https://example.org/x"}) == "https://example.org/x"
    assert om.clean_website({"contact:website": "www.example.org"}) == "https://www.example.org"
    assert om.clean_website({"website": "javascript:alert(1)"}) is None
    assert om.clean_website({"website": "not a url"}) is None
    assert om.clean_phone({"phone": "+27 31 000 0000; +27 31 111 1111"}) == "+27 31 000 0000"
    assert om.clean_phone({"phone": "call me"}) is None
    assert om.clean_min_age({"min_age": "18"}) == 18
    assert om.clean_min_age({"min_age": "adults"}) is None and om.clean_min_age({}) is None
    assert om.build_address({"addr:housenumber": "5", "addr:street": "Main Rd", "addr:suburb": "Morningside"}) == "5 Main Rd, Morningside"
    assert om.build_address({}) is None


# ---- transform -----------------------------------------------------------------------------------
def test_transform_builds_rows_without_inventing_anything():
    rows = pipeline.transform([el(1, "Club Test", amenity="nightclub", opening_hours="Fr-Sa 22:00-04:00")])
    row = rows[0]
    assert (row["category"], row["subcategory"], row["region"], row["osm_id"]) == ("Nightlife", "nightclub", "Durban", "node/1")
    assert row["open_evening"] is True and row["open_late"] is True        # 22:00-04:00 is open in the evening window and past 23:00
    assert row["opening_hours_raw"] == "Fr-Sa 22:00-04:00"
    for unknown in ("safety_score", "price_tier", "address", "website", "phone", "min_age"):
        assert row[unknown] is None, unknown
    assert row["source"] == "osm" and row["has_generator"] is False


def test_transform_skips_unnamed_coordinate_less_and_unmapped():
    rows = pipeline.transform([
        el(1, None, amenity="bar"),
        {"type": "node", "id": 2, "tags": {"name": "No Coords", "amenity": "bar"}},
        el(3, "Bench", amenity="bench"),
        el(4, "Motel Bar", amenity="bar", tourism="motel"),
        el(5, "Good Bar", amenity="bar"),
    ])
    assert [r["name"] for r in rows] == ["Good Bar"]


def test_transform_uses_centre_of_ways_and_keeps_raw_hours_when_unparseable():
    rows = pipeline.transform([el(9, "Big Casino", kind="way", lat=-29.9, lon=31.1, amenity="casino", opening_hours="sunrise-sunset")])
    assert (rows[0]["latitude"], rows[0]["longitude"]) == (-29.9, 31.1)
    assert (rows[0]["open_evening"], rows[0]["open_late"]) == (None, None)
    assert rows[0]["opening_hours"] == "sunrise-sunset"


def test_dedupe_by_name_and_proximity():
    near = [el(1, "Same Pub", lat=-29.8500, lon=31.0200, amenity="pub"),
            el(2, "Same Pub", lat=-29.8501, lon=31.0201, kind="way", amenity="pub", website="https://x.example", phone="+27 31 111 2222")]
    far = [el(3, "Chain Bar", lat=-29.85, lon=31.02, amenity="bar"), el(4, "Chain Bar", lat=-29.60, lon=30.40, amenity="bar")]
    rows = pipeline.transform(near + far)
    assert sorted(r["osm_id"] for r in rows) == ["node/3", "node/4", "way/2"]     # richer duplicate kept, far branch kept
    assert next(r for r in rows if r["osm_id"] == "way/2")["website"] == "https://x.example"


def test_description_does_not_claim_a_city():
    row = pipeline.transform([el(1, "Bar X", amenity="bar", region=None)])[0]
    assert "Durban" not in row["description"] and row["region"] is None


def test_legacy_candidate_file_still_loads():
    rows = pipeline.transform(pipeline.load_candidates_file(ROOT / "durban_candidates.json"))
    assert rows and all(r["category"] in ("Culture", "Entertainment", "Nature", "Beach", "Stay") for r in rows)
    assert any(r["category"] == "Culture" for r in rows)           # the old museums are still picked up


# ---- polite Overpass client -------------------------------------------------------------------------
class Reply:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def run_fetch(replies, **kwargs):
    calls, sleeps = [], []

    def post(url, **kw):
        calls.append((url, kw))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    result = overpass.fetch_elements(regions.CHUNKS[1], post=post, sleep=sleeps.append, log=lambda *_: None, **kwargs)
    return result, calls, sleeps


def test_fetch_sends_a_user_agent_and_returns_elements():
    result, calls, sleeps = run_fetch([Reply(200, {"elements": [{"id": 1}]})])
    assert result == [{"id": 1}] and sleeps == []
    assert "iKhaya" in calls[0][1]["headers"]["User-Agent"]


def test_fetch_retries_once_with_backoff_honouring_retry_after():
    result, calls, sleeps = run_fetch([Reply(429, headers={"Retry-After": "7"}), Reply(200, {"elements": []})])
    assert result == [] and sleeps == [7] and len(calls) == 2


def test_fetch_backoff_without_retry_after_and_cap():
    _, _, sleeps = run_fetch([Reply(504), Reply(200, {"elements": []})])
    assert sleeps == [30]
    assert overpass._backoff(5, None) == overpass.MAX_BACKOFF and overpass._backoff(0, "999") == overpass.MAX_BACKOFF


def test_fetch_gives_up_after_a_bounded_number_of_attempts():
    replies = [Reply(503)] * 10
    with pytest.raises(OverpassError):
        run_fetch(replies)
    assert len(replies) == 10 - len(overpass.OVERPASS_URLS) * overpass.ATTEMPTS_PER_ENDPOINT      # never loops forever


def test_fetch_falls_back_to_the_second_endpoint_after_timeouts():
    result, calls, _ = run_fetch([requests.Timeout(), requests.Timeout(), Reply(200, {"elements": [{"id": 5}]})])
    assert result == [{"id": 5}]
    assert calls[0][0] != calls[2][0]


def test_rejected_query_fails_immediately_without_retries():
    replies = [Reply(400), Reply(200, {"elements": []})]
    with pytest.raises(OverpassError):
        run_fetch(replies)
    assert len(replies) == 1


# ---- extraction: cache, order, failures -----------------------------------------------------------------
def fake_fetcher(data, calls):
    def fetch(chunk, log=print):
        calls.append(chunk.name)
        value = data[chunk.name]
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


def test_extract_uses_cache_on_the_second_run_and_refresh_forces_a_fetch(tmp_path):
    chunks = regions.chunks_for_regions(["North Coast"])
    data = {"iLembe": [el(1, "A Bar", amenity="bar")]}
    calls, sleeps = [], []
    kw = dict(fetch=fake_fetcher(data, calls), sleep=sleeps.append, log=lambda *_: None, pause=5)
    first, failed = overpass.extract_all(chunks, tmp_path, **kw)
    second, _ = overpass.extract_all(chunks, tmp_path, **kw)
    assert len(first) == len(second) == 1 and failed == []
    assert calls == ["iLembe"]                                      # second run made no request
    overpass.extract_all(chunks, tmp_path, refresh=True, **kw)
    assert calls == ["iLembe", "iLembe"]


def test_extract_pauses_between_requests_but_not_before_the_first(tmp_path):
    chunks = regions.CHUNKS[:3]
    calls, sleeps = [], []
    data = {c.name: [] for c in chunks}
    overpass.extract_all(chunks, tmp_path, fetch=fake_fetcher(data, calls), sleep=sleeps.append, log=lambda *_: None, pause=5)
    assert calls == [c.name for c in chunks] and sleeps == [5, 5]


def test_first_chunk_decides_the_region(tmp_path):
    chunks = regions.chunks_for_regions(["Pietermaritzburg", "Midlands"])
    shared = el(7, "Shared Bar", amenity="bar", region=None)
    data = {"Msunduzi (Pietermaritzburg)": [shared], "uMgungundlovu": [shared, el(8, "Midlands Pub", amenity="pub", region=None)]}
    elements, _ = overpass.extract_all(chunks, tmp_path, fetch=fake_fetcher(data, []), sleep=lambda s: None, log=lambda *_: None)
    assert {e["id"]: e["_region"] for e in elements} == {7: "Pietermaritzburg", 8: "Midlands"}


def test_a_failed_chunk_is_reported_and_does_not_stop_the_others(tmp_path):
    chunks = regions.chunks_for_regions(["North Coast", "Midlands"])
    data = {"iLembe": OverpassError("boom"), "uMgungundlovu": [el(2, "Midlands Bar", amenity="bar", region=None)]}
    elements, failed = overpass.extract_all(chunks, tmp_path, fetch=fake_fetcher(data, []), sleep=lambda s: None, log=lambda *_: None)
    assert failed == ["iLembe"] and len(elements) == 1


def test_offline_mode_never_fetches(tmp_path):
    calls = []
    elements, failed = overpass.extract_all(regions.CHUNKS[:2], tmp_path, offline=True, fetch=fake_fetcher({}, calls), log=lambda *_: None)
    assert calls == [] and elements == [] and len(failed) == 2


def test_stale_cache_is_refetched_but_offline_accepts_any_age(tmp_path):
    chunk = regions.CHUNKS[1]
    path = overpass.cache_file(tmp_path, chunk)
    overpass.write_cache(path, chunk, [el(1, "Old", amenity="bar")])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert overpass.read_cache(path, max_age_days=7) is None
    assert overpass.read_cache(path, max_age_days=None) is not None


def test_every_chunk_region_is_a_known_region_and_ids_are_unique():
    from app.taxonomy import REGIONS
    assert all(c.region in REGIONS for c in regions.CHUNKS)
    assert len({c.name for c in regions.CHUNKS}) == len(regions.CHUNKS)          # cache file names must differ
    assert len({overpass.cache_file("x", c) for c in regions.CHUNKS}) == len(regions.CHUNKS)
    assert regions.CHUNKS[0].region == "Pietermaritzburg"          # must precede the Midlands chunk


# ---- loader: idempotent, never touches curated places -------------------------------------------------------
def rows_for(*elements):
    return pipeline.transform(list(elements))


def test_load_is_idempotent(app):
    rows = rows_for(el(1, "Club A", amenity="nightclub"), el(2, "Cinema B", lat=-29.5, lon=30.9, amenity="cinema"))
    with app.app_context():
        before = Place.query.count()
        first = load_rows(rows)
        second = load_rows(rows)
        third = load_rows(rows)
        assert first["inserted"] == 2 and second["inserted"] == third["inserted"] == 0
        assert second["unchanged"] == 2
        assert Place.query.count() == before + 2


def test_curated_places_are_never_overwritten_or_duplicated(app):
    with app.app_context():
        curated = Place.query.filter_by(source="curated").first()
        snapshot = (curated.name, curated.category, curated.safety_score, curated.latitude, curated.region, curated.opening_hours)
        same_venue = el(5, curated.name, lat=curated.latitude + 0.0003, lon=curated.longitude, amenity="events_venue",
                        opening_hours="Mo-Su 10:00-23:00", website="https://evil.example")
        before = Place.query.count()
        stats = load_rows(rows_for(same_venue))
        assert stats["skipped_existing"] == 1 and stats["inserted"] == 0
        assert Place.query.count() == before
        again = db.session.get(Place, curated.id)
        assert (again.name, again.category, again.safety_score, again.latitude, again.region, again.opening_hours) == snapshot
        assert again.website is None and again.osm_id is None


def test_same_name_far_from_a_curated_place_is_a_different_venue(app):
    with app.app_context():
        curated = Place.query.filter_by(source="curated").first()
        far = el(6, curated.name, lat=curated.latitude + 0.5, lon=curated.longitude, amenity="bar")
        assert load_rows(rows_for(far))["inserted"] == 1


def test_existing_osm_rows_are_refreshed_in_place_but_keep_hand_made_values(app):
    first = rows_for(el(1, "Club A", amenity="nightclub", opening_hours="Fr-Sa 22:00-04:00"))
    changed = rows_for(el(1, "Club A", amenity="nightclub", opening_hours="Mo-Su 18:00-23:00", website="https://club.example"))
    with app.app_context():
        load_rows(first)
        place = Place.query.filter_by(osm_id="node/1").one()
        place.safety_score, place.price_tier, place.image_url = 4.0, "$$", "https://img.example/a.jpg"
        db.session.commit()
        stats = load_rows(changed)
        place = Place.query.filter_by(osm_id="node/1").one()
        assert stats["updated"] == 1 and Place.query.filter_by(osm_id="node/1").count() == 1
        assert place.opening_hours_raw == "Mo-Su 18:00-23:00" and place.website == "https://club.example"
        assert (place.safety_score, place.price_tier, place.image_url) == (4.0, "$$", "https://img.example/a.jpg")


def test_older_osm_rows_without_an_osm_id_are_adopted_not_duplicated(app):
    with app.app_context():
        db.session.add(Place(name="Old ETL Bar", category="Entertainment", latitude=-29.85, longitude=31.02, source="osm"))
        db.session.commit()
        before = Place.query.count()
        stats = load_rows(rows_for(el(11, "Old ETL Bar", lat=-29.85, lon=31.02, amenity="bar")))
        assert stats["inserted"] == 0 and stats["updated"] == 1 and Place.query.count() == before
        assert Place.query.filter_by(name="Old ETL Bar").one().osm_id == "node/11"


def test_invalid_rows_are_counted_and_ignored(app):
    good = rows_for(el(1, "Club A", amenity="nightclub"))[0]
    bad = [dict(good, category="Nonsense"), dict(good, latitude=999), dict(good, region="Atlantis"), {"name": "x"}]
    with app.app_context():
        stats = load_rows(bad)
        assert stats["invalid"] == 4 and stats["inserted"] == 0


# ---- snapshot ---------------------------------------------------------------------------------------------------
def test_snapshot_round_trip_is_idempotent_and_carries_attribution(app, tmp_path):
    from app.osm_snapshot import load_snapshot
    rows = rows_for(el(1, "Club A", amenity="nightclub"), el(2, "Cinema B", lat=-29.5, lon=30.9, amenity="cinema"))
    path = tmp_path / "osm_places.json"
    pipeline.write_snapshot(rows, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "ODbL" in data["attribution"] and data["count"] == 2
    with app.app_context():
        before = Place.query.count()
        assert load_snapshot(path)["inserted"] == 2
        assert load_snapshot(path)["inserted"] == 0
        assert Place.query.count() == before + 2
        assert load_snapshot(tmp_path / "missing.json") is None
        (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
        assert load_snapshot(tmp_path / "bad.json") is None


def test_app_loads_the_snapshot_at_startup_when_enabled(tmp_path, data_dir):
    pipeline.write_snapshot(rows_for(el(1, "Startup Club", amenity="nightclub")), data_dir / "osm_places.json")
    app = make_app(tmp_path, data_dir, LOAD_OSM_SNAPSHOT=True)
    try:
        with app.app_context():
            assert Place.query.filter_by(osm_id="node/1").count() == 1
        second = make_app(tmp_path, data_dir, LOAD_OSM_SNAPSHOT=True)            # restart: still one row
        with second.app_context():
            assert Place.query.filter_by(name="Startup Club").count() == 1
            db.engine.dispose()
    finally:
        with app.app_context():
            db.engine.dispose()


def test_snapshot_is_skipped_when_disabled(app, tmp_path):
    with app.app_context():
        assert Place.query.filter_by(source="osm").count() == 0


# ---- migration for osm_id -------------------------------------------------------------------------------------------
def test_osm_id_column_is_added_to_an_older_database(tmp_path, data_dir):
    con = sqlite3.connect(tmp_path / "test.db")
    from tests.test_phase2 import OLD_SCHEMA          # the schema from before Phases 2 and 3 (all original columns)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO places (id, name, category, latitude, longitude, source) VALUES (1, 'Keep Me', 'Beach', -29.8, 31.0, 'curated')")
    con.commit()
    con.close()
    app = make_app(tmp_path, data_dir)
    try:
        con = sqlite3.connect(tmp_path / "test.db")
        assert "osm_id" in {r[1] for r in con.execute("PRAGMA table_info(places)")}
        assert con.execute("SELECT name FROM places").fetchall() == [("Keep Me",)]
        con.close()
    finally:
        with app.app_context():
            db.engine.dispose()


# ---- summary + CLI --------------------------------------------------------------------------------------------------------
def test_summary_lists_regions_categories_and_gaps():
    rows = rows_for(el(1, "Club A", amenity="nightclub", region="Durban"), el(2, "Pub B", amenity="pub", region="Durban"),
                    el(3, "Cinema C", lat=-29.6, lon=30.4, amenity="cinema", region="Midlands"))
    text = pipeline.summarize(rows)
    assert "Durban" in text and "Midlands" in text and "All KZN" in text
    assert "Coverage gaps" in text and "South Coast: no Nightlife" in text and "Durban: no Entertainment" in text


def test_cli_dry_run_from_file_prints_summary_and_touches_nothing(tmp_path, capsys):
    import main as cli
    path = tmp_path / "chunk.json"
    path.write_text(json.dumps({"region": "Durban", "elements": [el(1, "Club A", amenity="nightclub", region=None)]}), encoding="utf-8")
    assert cli.main(["--from-file", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "1 places" in out and "Durban" in out and "Dry run" in out


def test_cli_refuses_to_write_a_partial_snapshot(tmp_path, capsys):
    import main as cli
    path = tmp_path / "chunk.json"
    path.write_text(json.dumps({"elements": [el(1, "Club A", amenity="nightclub")]}), encoding="utf-8")
    target = tmp_path / "snap.json"
    cli.main(["--from-file", str(path), "--dry-run", "--write-snapshot", str(target)])
    assert not target.exists() and "NOT written" in capsys.readouterr().out


def test_big_areas_are_split_into_smaller_queries():
    durban = regions.chunks_for_regions(["Durban"])
    assert len(durban) == 3 and {c.region for c in durban} == {"Durban"}
    queries = [overpass.build_query(c.area_id, keys=c.keys) for c in durban]
    assert 'nwr["amenity"' in queries[0] and 'nwr["leisure"' not in queries[0]
    assert 'nwr["leisure"' in queries[1] and 'karting' in queries[1] and 'nwr["amenity"' not in queries[1]
    assert 'nwr["tourism"' in queries[2] and 'nwr["amenity"' not in queries[2]
    # between them the parts ask for exactly what one full query asks for
    full = overpass.build_query(durban[0].area_id)
    assert sum(q.count("nwr[") for q in queries) == full.count("nwr[")
