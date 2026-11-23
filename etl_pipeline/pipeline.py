"""ETL: OpenStreetMap (Overpass API, no key needed) -> clean -> places table.

    extract()   fetch tourism features around Durban
    transform() drop accommodation / noise and map OSM tags onto our categories
    load()      insert the new ones, skipping places we already have
"""
import json
import re
from pathlib import Path

import requests

from app import db
from app.models import Place

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
# south, west, north, east
DURBAN_BBOX = (-30.0, 30.8, -29.7, 31.1)
USER_AGENT = "iKhayaKZN/1.0 (heritage + trip planner project)"

# OSM tourism=* values we skip: places to sleep, plain signage, and unlabelled artwork.
SKIP_TAGS = {
    "hotel", "guest_house", "apartment", "hostel", "caravan_site", "motel", "chalet",
    "camp_site", "information", "artwork", "yes", "alpine_hut", "wilderness_hut", "camp_pitch",
}
SKIP_NAME_WORDS = ("guest house", "backpackers", "bnb", "b&b", "lodge", "hotel", "chalet", "apartment")

# tourism tag -> (category, is_indoor)
TAG_MAP = {
    "museum": ("Culture", True),
    "gallery": ("Culture", True),
    "theme_park": ("Entertainment", False),
    "zoo": ("Nature", False),
    "aquarium": ("Entertainment", True),
    "viewpoint": ("Nature", False),
    "picnic_site": ("Nature", False),
    "attraction": ("Entertainment", False),
}


def _key(name):
    """Loose name key so "Kwa Muhle museum" and "KwaMuhle Museum" count as the same place."""
    return re.sub(r"\W+", "", str(name).lower())

def extract(bbox=DURBAN_BBOX, timeout=60):
    """Return raw candidate dicts from Overpass. Raises requests.RequestException on failure."""
    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:50];
    (
      node["tourism"]({s},{w},{n},{e});
      way["tourism"]({s},{w},{n},{e});
      relation["tourism"]({s},{w},{n},{e});
    );
    out center;
    """
    last_error = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(
                url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=timeout
            )
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            break
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            print(f"  ! {url} failed: {exc}")
    else:
        raise requests.RequestException(f"All Overpass endpoints failed: {last_error}")

    candidates = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not name or lat is None or lon is None:
            continue
        candidates.append({
            "name": name,
            "tourism": tags.get("tourism", ""),
            "latitude": lat,
            "longitude": lon,
            "address": tags.get("addr:street") or tags.get("addr:suburb") or "",
            "opening_hours": tags.get("opening_hours", ""),
            "website": tags.get("website", ""),
        })
    return candidates


def load_candidates_file(path):
    """Read candidates saved earlier (supports the older durban_candidates.json layout too)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for item in data:
        if "tourism" not in item:                       # old format used "category"
            item["tourism"] = str(item.get("category", "")).lower()
    return data


def save_candidates_file(candidates, path):
    Path(path).write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")


def transform(candidates):
    """Clean + categorise. Returns a list of dicts matching Place columns."""
    cleaned, seen = [], set()
    for c in candidates:
        name = " ".join(str(c.get("name", "")).split())
        tag = str(c.get("tourism", "")).lower()
        key = name.lower()
        if not name or _key(name) in seen or tag in SKIP_TAGS:
            continue
        if any(word in key for word in SKIP_NAME_WORDS):
            continue
        try:
            lat, lon = float(c["latitude"]), float(c["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        seen.add(_key(name))

        category, indoor = TAG_MAP.get(tag, ("Entertainment", False))
        lowered = key
        if any(w in lowered for w in ("beach", "bay", "pier", "lagoon")):
            category, indoor = "Beach", False
        elif any(w in lowered for w in ("park", "garden", "reserve", "forest", "trail")):
            category, indoor = "Nature", False
        elif any(w in lowered for w in ("museum", "gallery", "temple", "mosque", "memorial", "heritage")):
            category, indoor = "Culture", True

        address = str(c.get("address") or "").strip()
        hours = str(c.get("opening_hours") or "").strip()[:100]
        label = tag.replace("_", " ") or "attraction"
        cleaned.append({
            "name": name[:150],
            "description": f"{label.capitalize()} in the Durban area, sourced from OpenStreetMap.",
            "category": category,
            "address": (address + ", Durban" if address else "Durban, KZN")[:200],
            "opening_hours": hours or "Hours not listed",
            "latitude": lat,
            "longitude": lon,
            "is_indoor": indoor,
            "has_generator": False,
            "safety_score": 3.0,
            "price_tier": "$$",
            "source": "osm",
        })
    return cleaned


def load(rows):
    """Insert rows whose name isn't already in the table. Returns (inserted, skipped)."""
    existing = {_key(name) for (name,) in db.session.query(Place.name).all()}
    images = {}
    for place in Place.query.filter(Place.image_url != "").all():
        images.setdefault(place.category, place.image_url)    # reuse a known-good photo per category

    inserted = 0
    for row in rows:
        if _key(row["name"]) in existing:
            continue
        existing.add(_key(row["name"]))
        db.session.add(Place(image_url=images.get(row["category"], ""), **row))
        inserted += 1
    db.session.commit()
    return inserted, len(rows) - inserted
