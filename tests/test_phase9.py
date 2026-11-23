"""Food and shopping in the OSM ETL: mapping, query, and the per-subcategory cap."""
import pytest

from app.taxonomy import SUBCATEGORIES, is_valid_subcategory
from etl_pipeline import osm_mapping as om
from etl_pipeline.overpass import build_query
from etl_pipeline.pipeline import MAX_PER_REGION_SUBCATEGORY, cap_rows, transform
from etl_pipeline.regions import CHUNKS


@pytest.mark.parametrize("tags,expected", [
    ({"amenity": "restaurant"}, ("Food", "restaurant", True)),
    ({"amenity": "cafe"}, ("Food", "cafe", True)),
    ({"amenity": "fast_food"}, ("Food", "fast_food", True)),
    ({"amenity": "food_court"}, ("Food", "food_court", True)),
    ({"amenity": "ice_cream"}, ("Food", "ice_cream", True)),
    ({"amenity": "marketplace"}, ("Food", "market", False)),
    ({"shop": "mall"}, ("Shopping", "mall", True)),
    ({"shop": "department_store"}, ("Shopping", "department_store", True)),
    ({"shop": "supermarket"}, ("Shopping", "supermarket", True)),
    ({"shop": "craft"}, ("Shopping", "craft", True)),
    ({"shop": "gift"}, ("Shopping", "gift", True)),
    ({"shop": "souvenir"}, ("Shopping", "souvenir", True)),
])
def test_food_and_shopping_tags_are_classified(tags, expected):
    category, sub, indoor, _ = om.classify(dict(tags, name="X"))
    assert (category, sub, indoor) == expected
    assert is_valid_subcategory(sub) and sub in SUBCATEGORIES[category]


def test_other_shop_types_are_not_imported():
    assert om.classify({"shop": "clothes", "name": "X"}) is None
    assert om.classify({"shop": "convenience", "name": "X"}) is None


def test_a_bar_is_still_nightlife_and_a_hotel_still_a_stay():
    assert om.classify({"amenity": "bar", "name": "X"})[0] == "Nightlife"
    assert om.classify({"tourism": "hotel", "amenity": "restaurant", "name": "X"})[0] == "Stay"


def test_every_chunk_still_asks_for_shops_somewhere():
    keys = {k for c in CHUNKS for k in (c.keys or ("amenity", "leisure", "sport", "tourism", "shop"))}
    assert "shop" in keys
    queries = " ".join(build_query(c.area_id, keys=c.keys) for c in CHUNKS)
    assert '"shop"~"^(mall|department_store|supermarket|craft|gift|souvenir)$"' in queries
    assert "restaurant" in queries and "marketplace" in queries


def _el(i, tags, lat=-29.85, lon=31.0, region="Durban"):
    return {"type": "node", "id": i, "lat": lat + i * 0.01, "lon": lon, "tags": tags, "_region": region}


def test_transform_builds_food_rows_with_unknowns_left_unknown():
    rows = transform([_el(1, {"amenity": "cafe", "name": "Beans"})])
    row = rows[0]
    assert row["category"] == "Food" and row["subcategory"] == "cafe"
    assert row["price_tier"] is None and row["safety_score"] is None and row["opening_hours"] is None


def test_cap_keeps_best_described_places_per_region_and_subcategory():
    elements = []
    for i in range(1, 6):
        tags = {"amenity": "cafe", "name": f"Cafe {i}"}
        if i >= 4:                                           # the two with the most information
            tags.update({"website": "https://example.org/a", "phone": "031 555 0100", "opening_hours": "Mo-Su 08:00-17:00"})
        elements.append(_el(i, tags))
    rows = cap_rows(transform(elements), limit=2)
    assert {r["name"] for r in rows} == {"Cafe 4", "Cafe 5"}


def test_cap_is_per_region_and_per_subcategory_and_ignores_other_categories():
    base = lambda name, cat, sub, region: {"name": name, "category": cat, "subcategory": sub, "region": region,
                                           "osm_id": name, "tags": ""}
    rows = ([base(f"c{i}", "Food", "cafe", "Durban") for i in range(5)]
            + [base(f"r{i}", "Food", "restaurant", "Durban") for i in range(5)]
            + [base(f"d{i}", "Food", "cafe", "Midlands") for i in range(5)]
            + [base(f"b{i}", "Nightlife", "bar", "Durban") for i in range(5)])
    kept = cap_rows(rows, limit=3)
    assert sum(r["subcategory"] == "cafe" and r["region"] == "Durban" for r in kept) == 3
    assert sum(r["subcategory"] == "restaurant" for r in kept) == 3
    assert sum(r["subcategory"] == "cafe" and r["region"] == "Midlands" for r in kept) == 3
    assert sum(r["category"] == "Nightlife" for r in kept) == 5


def test_cap_is_deterministic_and_default_is_150():
    assert MAX_PER_REGION_SUBCATEGORY == 150
    rows = transform([_el(i, {"amenity": "restaurant", "name": f"R{i}"}) for i in range(1, 8)])
    assert cap_rows(rows, 3) == cap_rows(list(reversed(rows)), 3)


# ---- Mix: one subcategory (e.g. malls) cannot fill the results
def test_diversify_caps_each_subcategory_when_asked():
    from ml_engine.recommender import diversify
    items = ([{"id": i, "category": "Shopping", "subcategory": "mall"} for i in range(6)]
             + [{"id": 10 + i, "category": "Shopping", "subcategory": "craft"} for i in range(3)])
    top = diversify(items, 6, cap=6, sub_cap=2)
    assert [i["subcategory"] for i in top[:4]] == ["mall", "mall", "craft", "craft"]
    assert len(top) == 6                                                  # still filled from the leftovers


def test_sub_cap_ignores_places_without_a_subcategory():
    from ml_engine.recommender import diversify
    items = [{"id": i, "category": "Beach", "subcategory": None} for i in range(5)]
    assert len(diversify(items, 5, cap=5, sub_cap=1)) == 5


def test_tourist_mode_reports_and_applies_the_subcategory_cap(client):
    data = client.get("/api/recommend?tourist=1&limit=12").get_json()
    assert data["tourist_mode"]["cap_per_subcategory"] == 2
    seen = {}
    for r in data["results"]:
        if r.get("subcategory"):
            seen[(r["category"], r["subcategory"])] = seen.get((r["category"], r["subcategory"]), 0) + 1
    assert all(n <= 2 for n in seen.values()) or len(data["results"]) == 12  # leftovers may refill when data is thin
    assert client.get("/api/recommend?limit=12").get_json()["tourist_mode"]["cap_per_subcategory"] is None
