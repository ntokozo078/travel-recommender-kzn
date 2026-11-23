"""Loader and validator for app/clan_data.py."""
import hashlib
import json
from pathlib import Path

from app.clan_data import ClanStore, normalize
from tests.conftest import FIXTURE_CLANS, ROOT, write_data


def store_with(tmp_path, enrichment, clans=FIXTURE_CLANS):
    data = write_data(tmp_path / "d", clans, enrichment)
    return ClanStore(data / "surnames.json", data / "clans_enrichment.json")


def warned(store, fragment):
    return any(fragment in w for w in store.warnings)


# ---- normalisation -----------------------------------------------------
def test_normalize_ignores_case_accents_punctuation_and_doubled_letters():
    assert normalize("Ntombela") == normalize("Ntombella") == normalize("NTOMBÉLA") == normalize(" n-tombela ")
    assert normalize("") == normalize(None) == ""


# ---- happy path --------------------------------------------------------
def test_merges_base_and_enrichment_without_changing_base_fields(tmp_path):
    store = store_with(tmp_path, {"Ndlovu": {"meaning": "DUMMY", "confidence": "unverified"}})
    ndlovu = store.get("ndlovu")
    assert ndlovu["origins"] == "Test origin text."            # base fields untouched
    assert ndlovu["enrichment"]["meaning"] == "DUMMY"
    assert ndlovu["has_enrichment"] is True
    assert ndlovu["praise_names"] == ["Delta", "Epsilon"]
    assert store.warnings == []


def test_unenriched_clans_get_all_null_fields(tmp_path):
    zulu = store_with(tmp_path, {}).get("Zulu")
    assert zulu["has_enrichment"] is False
    assert all(value is None for value in zulu["enrichment"].values())


def test_underscore_keys_and_missing_file_are_fine(tmp_path):
    assert store_with(tmp_path, {"_format": "note"}).warnings == []
    data = write_data(tmp_path / "d2", enrichment=None)
    assert ClanStore(data / "surnames.json", data / "nope.json").warnings == []


def test_shipped_enrichment_file_is_valid():
    store = ClanStore(ROOT / "data" / "surnames.json", ROOT / "data" / "clans_enrichment.json")
    assert store.warnings == []
    assert len(store.clans) == 224


def test_loading_never_modifies_the_base_json():
    path = ROOT / "data" / "surnames.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    ClanStore(path, ROOT / "data" / "clans_enrichment.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


# ---- validation warnings (never crashes, bad values dropped) -----------
def test_unknown_field_warns_and_is_ignored(tmp_path):
    store = store_with(tmp_path, {"Ndlovu": {"bogus": 1, "meaning": "DUMMY"}})
    assert warned(store, "unknown field 'bogus'")
    assert "bogus" not in store.get("Ndlovu")["enrichment"]


def test_bad_coordinates_warn_and_are_dropped(tmp_path):
    for lat, lng in [(999, 31), (-29, 181), ("x", 31), (-29, None)]:
        store = store_with(tmp_path, {"Ndlovu": {"origin": {"summary": "DUMMY", "lat": lat, "lng": lng}}})
        origin = store.get("Ndlovu")["enrichment"]["origin"]
        assert warned(store, "coordinates") or warned(store, "lat and lng"), (lat, lng)
        assert origin["lat"] is None and origin["lng"] is None


def test_valid_coordinates_are_kept(tmp_path):
    store = store_with(tmp_path, {"Ndlovu": {"origin": {"lat": -29.5, "lng": 30.5}}})
    assert store.warnings == []
    assert store.get("Ndlovu")["enrichment"]["origin"]["lat"] == -29.5


def test_unknown_origin_field_warns(tmp_path):
    assert warned(store_with(tmp_path, {"Ndlovu": {"origin": {"country": "x"}}}), "unknown field 'country'")


def test_invalid_confidence_warns_and_is_dropped(tmp_path):
    store = store_with(tmp_path, {"Ndlovu": {"confidence": "certain"}})
    assert warned(store, "must be one of")
    assert store.get("Ndlovu")["enrichment"]["confidence"] is None


def test_verified_without_sources_warns(tmp_path):
    assert warned(store_with(tmp_path, {"Ndlovu": {"confidence": "verified"}}), "needs at least one source")
    assert not warned(store_with(tmp_path, {"Ndlovu": {"confidence": "verified", "sources": ["DUMMY"]}}), "needs at least one source")


def test_wrong_types_warn(tmp_path):
    store = store_with(tmp_path, {"Ndlovu": {"sources": "text", "izithakazelo_notes": ["Delta"], "meaning": 5}})
    assert len([w for w in store.warnings if "expected" in w]) == 3


def test_related_clan_must_exist(tmp_path):
    assert warned(store_with(tmp_path, {"Ndlovu": {"related_clans": ["Nobody"]}}), "related clan 'Nobody'")


def test_enrichment_for_unknown_surname_warns(tmp_path):
    store = store_with(tmp_path, {"Nowhere": {"meaning": "DUMMY"}})
    assert warned(store, "no matching clan")
    assert len(store.clans) == len(FIXTURE_CLANS["clans"])


def test_duplicate_normalised_keys_warn(tmp_path):
    assert warned(store_with(tmp_path, {"Ndlovu": {}, "ndlovu": {}}), "duplicates")


def test_alt_spelling_clash_with_another_clan_warns(tmp_path):
    store = store_with(tmp_path, {"Ndlovu": {"alt_spellings": ["Zulu"]}})
    assert warned(store, "clashes")
    assert store.get("Zulu")["surname"] == "Zulu"            # real surname wins


def test_malformed_enrichment_file_does_not_crash(tmp_path):
    data = write_data(tmp_path / "d", enrichment=None)
    (data / "clans_enrichment.json").write_text("{not json", encoding="utf-8")
    store = ClanStore(data / "surnames.json", data / "clans_enrichment.json")
    assert warned(store, "could not read")
    assert len(store.clans) == len(FIXTURE_CLANS["clans"])
