"""Area awareness: SAPS file -> safety_context.json -> optional `area_awareness` on places.

All station names and numbers below are made-up test fixtures, not real statistics.
"""
import json
import re

import pytest

from app import db
from tests.conftest import make_app, write_data
from etl_pipeline import safety

LONG_CSV = """Station,Category,Count,Period
Testville Central,Common robbery,12,2023/2024
Testville Central,Burglary at residential premises,30,2023/2024
Testville Central,Shoplifting,99,2023/2024
Testville Central,Robbery at business premises,abc,2023/2024
Nowhere Bay,Common robbery,5,2023/2024
Twin,Common robbery,7,2023/2024
"""
WIDE_CSV = """Station,Category,2021/2022,2022/2023,2023/2024
Testville Central,Common robbery,1,2,3
Testville Central,Burglary at residential premises,4,5,6
"""
POLICE = [
    {"type": "node", "id": 1, "lat": -29.85, "lon": 31.02, "tags": {"name": "Testville Central Police Station"}},
    {"type": "way", "id": 2, "center": {"lat": -29.0, "lon": 30.0}, "tags": {"name": "SAPS Twin"}},
    {"type": "node", "id": 3, "lat": -28.0, "lon": 30.5, "tags": {"name": "Twin Police Station"}},
    {"type": "node", "id": 4, "lat": -29.5, "lon": 30.9, "tags": {"amenity": "police"}},       # no name: ignored
]


def write(tmp_path, text, name="saps.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_station_names_are_normalised():
    assert safety.normalise_station("SAPS Durban Central Police Station") == safety.normalise_station("Durban Central")
    assert safety.normalise_station("") == ""


def test_long_format_keeps_only_wanted_categories_and_skips_bad_counts(tmp_path):
    period, stations = safety.read_saps_csv(write(tmp_path, LONG_CSV))
    assert period == "2023/2024"
    assert stations["Testville Central"] == {"Common robbery": 12, "Burglary at residential premises": 30}
    assert "Shoplifting" not in stations["Testville Central"]          # not in the default categories
    assert "Robbery at business premises" not in stations["Testville Central"]   # "abc" is skipped, not zero


def test_categories_can_be_chosen(tmp_path):
    _, stations = safety.read_saps_csv(write(tmp_path, LONG_CSV), ["shoplifting"])
    assert stations == {"Testville Central": {"Shoplifting": 99}}


def test_wide_format_uses_the_latest_period_column(tmp_path):
    period, stations = safety.read_saps_csv(write(tmp_path, WIDE_CSV))
    assert period == "2023/2024"
    assert stations["Testville Central"]["Common robbery"] == 3


def test_missing_columns_raise_a_clear_error(tmp_path):
    with pytest.raises(safety.SafetyDataError):
        safety.read_saps_csv(write(tmp_path, "Name,Value\nA,1\n"))


def test_matching_is_exact_never_fuzzy_and_drops_ambiguous_names(tmp_path):
    _, stations = safety.read_saps_csv(write(tmp_path, LONG_CSV))
    context, unmatched = safety.build_context("2023/2024", stations, POLICE)
    assert [s["name"] for s in context["stations"]] == ["Testville Central"]
    assert set(unmatched) == {"Nowhere Bay", "Twin"}                   # "Twin" matches two OSM stations: left out
    station = context["stations"][0]
    assert (station["latitude"], station["longitude"]) == (-29.85, 31.02)
    assert context["source"] == safety.SOURCE_NAME and "not a safety rating" in context["note"]


def _context():
    return {"source": safety.SOURCE_NAME, "period": "2023/2024", "generated": "2026-11-24", "note": safety.NOTE,
            "stations": [{"name": "Testville Central", "latitude": -29.85, "longitude": 31.02,
                          "categories": {"Common robbery": 12}}]}


def test_area_awareness_uses_the_nearest_station_within_range():
    info = safety.area_awareness(_context(), -29.86, 31.03)
    assert info["station"] == "Testville Central" and info["distance_km"] < 3
    assert info["categories"] == [{"category": "Common robbery", "count": 12}]
    assert safety.area_awareness(_context(), -25.0, 28.0) is None      # nothing close enough
    assert safety.area_awareness(None, -29.8, 31.0) is None


def test_load_context_tolerates_missing_and_broken_files(tmp_path):
    assert safety.load_context(tmp_path / "nope.json") is None
    assert safety.load_context(write(tmp_path, "{not json", "bad.json")) is None
    assert safety.load_context(write(tmp_path, '{"stations": 5}', "odd.json")) is None


@pytest.fixture
def area_client(tmp_path):
    (tmp_path / "area").mkdir()
    data = write_data(tmp_path / "area" / "data")
    (data / "safety_context.json").write_text(json.dumps(_context()), encoding="utf-8")
    application = make_app(tmp_path / "area", data)
    yield application.test_client()
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


def test_places_get_an_optional_area_object_and_scores_do_not_change(area_client, client):
    with_area = area_client.get("/api/recommend?lat=-29.85&lon=31.02&limit=50").get_json()
    without = client.get("/api/recommend?lat=-29.85&lon=31.02&limit=50").get_json()
    assert any("area_awareness" in r for r in with_area["results"])
    assert not any("area_awareness" in r for r in without["results"])
    assert [(r["id"], r["score"]) for r in with_area["results"]] == [(r["id"], r["score"]) for r in without["results"]]
    assert [r["safety_score"] for r in with_area["results"]] == [r["safety_score"] for r in without["results"]]


def test_near_endpoint_and_footer_credit(area_client, client):
    near = area_client.get("/api/places/near?lat=-29.85&lon=31.02&limit=3").get_json()["results"]
    assert near and "area_awareness" in near[0]
    page = area_client.get("/").get_data(as_text=True)
    assert safety.SOURCE_NAME in page and "2023/2024" in page
    assert safety.SOURCE_NAME not in client.get("/").get_data(as_text=True)


def test_wording_never_labels_an_area_safe_or_unsafe():
    texts = [safety.NOTE, safety.SOURCE_NAME, json.dumps(safety.area_awareness(_context(), -29.85, 31.02))]
    for text in texts:
        assert not re.search(r"\b(unsafe|dangerous|safe area|high[- ]crime|crime[- ]ridden)\b", text, re.I)
    js = open("app/static/js/app.js", encoding="utf-8").read()
    block = js[js.index("function areaBlock"):js.index("function tripCard")]
    assert not re.search(r"\bunsafe|dangerous|high[- ]crime\b", block, re.I)


def test_build_script_stops_clearly_without_a_saps_file(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("bsc", Path(__file__).resolve().parents[1] / "scripts" / "build_safety_context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--input", str(tmp_path / "missing.csv")])
    assert "not found" in str(exc.value).lower()


def test_build_script_end_to_end_offline(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("bsc2", Path(__file__).resolve().parents[1] / "scripts" / "build_safety_context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    police = tmp_path / "police.json"
    police.write_text(json.dumps({"elements": POLICE}), encoding="utf-8")
    out = tmp_path / "out.json"
    assert mod.main(["--input", str(write(tmp_path, LONG_CSV)), "--police-file", str(police), "--output", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [s["name"] for s in data["stations"]] == ["Testville Central"] and data["period"] == "2023/2024"
