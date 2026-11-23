"""Clan search / suggest / detail API, the no-enrichment fallback, and the old endpoint's shape."""
import json

from app import db
from app.models import ClanCorrection
from tests.conftest import ROOT


def get(client, url):
    response = client.get(url)
    return response.status_code, response.get_json()


# ---- search: spelling tolerance ---------------------------------------
def test_search_tolerates_case_accents_and_doubled_letters(client):
    for query in ("Ntombela", "ntombella", "NTOMBÉLA", "  ntombela  "):
        status, body = get(client, f"/api/heritage/clans/search?q={query}")
        assert status == 200
        assert body["surname_match"]["surname"] == "Ntombela", query
        assert body["did_you_mean"] == []


def test_search_matches_alternative_spellings(client):
    _, body = get(client, "/api/heritage/clans/search?q=Ndhlovu")
    assert body["surname_match"]["surname"] == "Ndlovu"
    assert body["matched_via"] == "alt_spelling"


def test_search_suggests_did_you_mean_for_typos(client):
    _, body = get(client, "/api/heritage/clans/search?q=Buthelesi")
    assert body["surname_match"] is None and body["praise_match"] is None
    assert "Buthelezi" in [s["text"] for s in body["did_you_mean"]]


def test_search_with_nothing_found_or_empty_query_is_not_an_error(client):
    for query in ("qqqqzzzz", "", "   "):
        status, body = get(client, f"/api/heritage/clans/search?q={query}")
        assert status == 200
        assert body["surname_match"] is None and body["praise_match"] is None


def test_search_query_is_length_capped(client):
    _, body = get(client, "/api/heritage/clans/search?q=" + "a" * 500)
    assert len(body["query"]) == 80


# ---- search: reverse lookup of praise names ---------------------------
def test_praise_name_returns_every_clan_that_uses_it(client):
    _, body = get(client, "/api/heritage/clans/search?q=beta")
    assert body["surname_match"] is None
    assert body["praise_match"]["name"] == "Beta"
    assert [c["surname"] for c in body["praise_match"]["clans"]] == ["Kheswa", "Lamula", "Ntombela"]


def test_praise_lookup_is_also_spelling_tolerant(client):
    _, body = get(client, "/api/heritage/clans/search?q=BETTA")
    assert len(body["praise_match"]["clans"]) == 3


# ---- suggest (autocomplete) -------------------------------------------
def test_suggest_prefix_matches(client):
    _, body = get(client, "/api/heritage/clans/suggest?q=ntom")
    assert [s["text"] for s in body["suggestions"]] == ["Ntombela"]


def test_suggest_includes_praise_names_and_alt_spellings(client):
    kinds = {s["text"]: s["kind"] for s in get(client, "/api/heritage/clans/suggest?q=nd")[1]["suggestions"]}
    assert kinds["Ndlovu"] == "surname" and kinds["Ndhlovu"] == "alt_spelling"
    assert get(client, "/api/heritage/clans/suggest?q=alp")[1]["suggestions"][0]["kind"] == "praise_name"


def test_suggest_empty_query_and_limit(client):
    assert get(client, "/api/heritage/clans/suggest?q=")[1]["suggestions"] == []
    assert len(get(client, "/api/heritage/clans/suggest?q=e&limit=1")[1]["suggestions"]) <= 1


# ---- full record --------------------------------------------------------
def test_detail_resolves_related_clans_to_links(client):
    status, body = get(client, "/api/heritage/clans/ndlovu")
    related = {r["name"]: r for r in body["enrichment"]["related_clans"]}
    assert status == 200 and body["surname"] == "Ndlovu"
    assert related["Zulu"]["found"] is True and related["Zulu"]["link"] == "#/heritage/clans?q=Zulu"
    assert related["Missing Clan"]["found"] is False and related["Missing Clan"]["link"] is None


def test_detail_unknown_surname_is_json_404(client):
    status, body = get(client, "/api/heritage/clans/Nobody")
    assert status == 404 and "error" in body


# ---- fallback when a clan has no enrichment ---------------------------
def test_unenriched_clan_still_returns_praise_names_and_null_fields(client):
    status, body = get(client, "/api/heritage/clans/Zulu")
    assert status == 200
    assert body["has_enrichment"] is False
    assert body["praise_names"] == ["Eta"]
    assert all(value is None for value in body["enrichment"].values())
    assert body["base_origin"] is None            # generic placeholder text is not passed on as a fact


def test_real_base_origin_text_is_kept(client):
    assert get(client, "/api/heritage/clans/Ndlovu")[1]["base_origin"] == "Test origin text."


# ---- the original endpoint must not change -----------------------------
def test_old_clans_endpoint_returns_exactly_the_base_file(real_client):
    expected = json.loads((ROOT / "data" / "surnames.json").read_text(encoding="utf-8"))
    status, body = get(real_client, "/api/heritage/clans")
    assert status == 200
    assert list(body) == ["clans"]
    assert body == expected
    assert len(body["clans"]) == 224
    assert all(set(c) == {"surname", "praise_poetry", "origins"} for c in body["clans"])


def test_other_heritage_endpoints_unchanged(real_client):
    assert get(real_client, "/api/heritage/herbs")[1]["items"]
    assert get(real_client, "/api/heritage/nope")[0] == 404


# ---- nearby places -------------------------------------------------------
def test_places_near_is_sorted_by_distance_and_limited(client):
    status, body = get(client, "/api/places/near?lat=-29.8587&lon=31.0218&limit=5")
    distances = [p["distance_km"] for p in body["results"]]
    assert status == 200 and len(distances) == 5
    assert distances == sorted(distances)


def test_places_near_rejects_bad_input(client):
    for query in ("", "?lat=1", "?lat=abc&lon=1", "?lat=999&lon=1", "?lat=nan&lon=1"):
        assert client.get("/api/places/near" + query).status_code == 400, query


# ---- suggest-a-correction -----------------------------------------------
def post(client, **payload):
    return client.post("/api/clan-corrections", json=payload)


def test_correction_is_stored(client, app):
    assert post(client, surname="Ndlovu", message="Please check this.", contact="me").status_code == 201
    with app.app_context():
        row = ClanCorrection.query.one()
        assert (row.surname, row.message, row.contact) == ("Ndlovu", "Please check this.", "me")


def test_correction_validation(client):
    assert client.post("/api/clan-corrections", data="a=1").status_code == 415
    assert post(client, surname="Nobody", message="Long enough message").status_code == 404
    assert post(client, surname="Ndlovu", message="hi").status_code == 400
    assert post(client, surname="Ndlovu", message="x" * 1001).status_code == 400


def test_correction_honeypot_stores_nothing(client, app):
    assert post(client, surname="Ndlovu", message="Buy my stuff", website="http://spam").status_code == 201
    with app.app_context():
        assert ClanCorrection.query.count() == 0


def test_correction_is_rate_limited(client):
    codes = [post(client, surname="Ndlovu", message=f"Message number {i}").status_code for i in range(7)]
    assert codes == [201] * 5 + [429] * 2


def test_corrections_never_touch_places(client, app):
    from app.models import Place
    with app.app_context():
        before = Place.query.count()
    post(client, surname="Ndlovu", message="Please check this.")
    with app.app_context():
        assert Place.query.count() == before > 0
