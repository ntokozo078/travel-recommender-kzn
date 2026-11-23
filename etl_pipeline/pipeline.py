"""ETL steps for OpenStreetMap places.

    extract   etl_pipeline/overpass.py  (polite, cached, one chunk per district)
    transform this module               (elements -> clean rows; pure, no network)
    load      etl_pipeline/loader.py    (idempotent upsert into the database)
"""
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.taxonomy import CATEGORIES, REGIONS
from etl_pipeline import osm_mapping as om
from ml_engine.recommender import haversine_km

# Food and shopping are far more common than the other categories (thousands of cafes), so they are capped:
# per region and subcategory, keep the best-described places. This stops one subcategory (or one big city)
# from drowning the rest. Other categories are never capped.
CAPPED_CATEGORIES = ("Food", "Shopping")
MAX_PER_REGION_SUBCATEGORY = 150
ATTRIBUTION = "Contains data from OpenStreetMap contributors, available under the Open Database Licence (ODbL)."
DUPLICATE_RADIUS_M = 150


def name_key(name):
    """Loose name key so "Kwa Muhle museum" and "KwaMuhle Museum" count as the same place."""
    return re.sub(r"\W+", "", str(name).lower())


class ProximityIndex:
    """Find an earlier place with the same (loose) name within DUPLICATE_RADIUS_M."""

    CELL = 0.002          # degrees, about 220 m

    def __init__(self):
        self._cells = defaultdict(list)

    def _cell(self, lat, lon):
        return round(lat / self.CELL), round(lon / self.CELL)

    def find(self, name, lat, lon, radius_m=DUPLICATE_RADIUS_M):
        key, (cy, cx) = name_key(name), self._cell(lat, lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for other_key, olat, olon, payload in self._cells.get((cy + dy, cx + dx), ()):
                    if other_key == key and haversine_km(lat, lon, olat, olon) * 1000 <= radius_m:
                        return payload
        return None

    def add(self, name, lat, lon, payload=True):
        self._cells[self._cell(lat, lon)].append((name_key(name), lat, lon, payload))


# ---------------------------------------------------------------- legacy candidate files
def load_candidates_file(path):
    """Read elements from a saved file. Accepts a cache chunk ({"elements": [...]}) or the old
    durban_candidates.json list ({name, tourism, latitude, longitude, ...})."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [dict(el, _region=el.get("_region") or data.get("region")) for el in data.get("elements", [])]
    elements = []
    for item in data:
        tourism = str(item.get("tourism") or item.get("category") or "").lower()
        tags = {"name": item.get("name"), "tourism": tourism,
                "opening_hours": item.get("opening_hours"), "addr:street": item.get("address")}
        elements.append({"type": "legacy", "id": None, "lat": item.get("latitude"), "lon": item.get("longitude"),
                         "tags": {k: v for k, v in tags.items() if v}})
    return elements


# ---------------------------------------------------------------- transform
def _coords(el):
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lon = el.get("lon", (el.get("center") or {}).get("lon"))
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def transform(elements):
    """Clean + categorise OSM elements into rows matching the Place columns."""
    rows, seen = [], ProximityIndex()
    # Richer elements first so, of two entries for one venue (node + building), we keep the better one.
    ordered = sorted(elements, key=lambda e: (-len(e.get("tags") or {}), str(e.get("type")), e.get("id") or 0))
    for el in ordered:
        tags = el.get("tags") or {}
        name = " ".join(str(tags.get("name", "")).split())[:150]
        coords = _coords(el)
        verdict = om.classify(tags) if name else None
        if not name or coords is None or verdict is None:
            continue
        lat, lon = coords
        if seen.find(name, lat, lon):
            continue
        seen.add(name, lat, lon)

        category, subcategory, indoor, source_tag = verdict
        region = el.get("_region")
        raw_hours = " ".join(str(tags.get("opening_hours", "")).split())[:255] or None
        evening, late = om.parse_opening_hours(raw_hours)
        label = subcategory.replace("_", " ") if subcategory else source_tag.split("=")[1].replace("_", " ")
        rows.append({
            "osm_id": f"{el['type']}/{el['id']}" if el.get("id") is not None else None,
            "name": name,
            "description": f"{label.capitalize()}{' in the ' + region + ' region' if region else ''}, listed on OpenStreetMap.",
            "category": category,
            "subcategory": subcategory,
            "region": region if region in REGIONS else None,
            "address": om.build_address(tags),
            "opening_hours": raw_hours[:100] if raw_hours else None,
            "opening_hours_raw": raw_hours,
            "website": om.clean_website(tags),
            "phone": om.clean_phone(tags),
            "min_age": om.clean_min_age(tags),
            "open_evening": evening,
            "open_late": late,
            "tags": om.build_tags(tags, source_tag),
            "latitude": lat,
            "longitude": lon,
            "is_indoor": indoor,
            "has_generator": False,
            "safety_score": None,          # OSM has no ratings: NULL = not rated
            "price_tier": None,            # OSM has no prices: unknown
            "source": "osm",
        })
    rows = cap_rows(rows)
    rows.sort(key=lambda r: (r["region"] or "~", r["category"], r["name"].lower()))
    return rows


def _richness(row):
    """How much real information a row carries: used only to choose which places survive the cap."""
    return sum(1 for key in ("opening_hours_raw", "website", "phone", "address") if row.get(key))         + (1 if "live_music" in (row.get("tags") or "") or "wheelchair" in (row.get("tags") or "") else 0)


def cap_rows(rows, limit=MAX_PER_REGION_SUBCATEGORY):
    """Keep at most `limit` Food/Shopping rows per (region, subcategory), best-described first
    (ties broken by name so the result is stable). Everything else passes through untouched."""
    groups, out = defaultdict(list), []
    for row in rows:
        if row["category"] in CAPPED_CATEGORIES:
            groups[(row["region"], row["subcategory"])].append(row)
        else:
            out.append(row)
    for group in groups.values():
        group.sort(key=lambda r: (-_richness(r), r["name"].lower(), r["osm_id"] or ""))
        out.extend(group[:limit])
    return out


# ---------------------------------------------------------------- reporting + snapshot
def summarize(rows):
    """Text table of rows per region and category, plus the gaps worth looking at."""
    focus = ("Nightlife", "Entertainment", "Food", "Shopping")
    counts = defaultdict(int)
    for r in rows:
        counts[(r["region"] or "Unassigned", r["category"])] += 1
    regions = [r for r in REGIONS if any(k[0] == r for k in counts)]
    if any(k[0] == "Unassigned" for k in counts):
        regions.append("Unassigned")

    head = f"{'Region':<18}" + "".join(f"{c[:10]:>12}" for c in CATEGORIES) + f"{'Total':>8}"
    lines = [head, "-" * len(head)]
    for region in regions:
        cells = [counts[(region, c)] for c in CATEGORIES]
        lines.append(f"{region:<18}" + "".join(f"{n:>12}" for n in cells) + f"{sum(cells):>8}")
    totals = [sum(counts[(r, c)] for r in regions) for c in CATEGORIES]
    lines += ["-" * len(head), f"{'All KZN':<18}" + "".join(f"{n:>12}" for n in totals) + f"{sum(totals):>8}"]

    subs = defaultdict(int)
    for r in rows:
        if r["subcategory"]:
            subs[r["subcategory"]] += 1
    if subs:
        lines += ["", "By subcategory: " + ", ".join(f"{k} {v}" for k, v in sorted(subs.items(), key=lambda kv: (-kv[1], kv[0])))]

    gaps = [f"{region}: no {cat}" for region in REGIONS if region != "Other KZN"
            for cat in focus if counts[(region, cat)] == 0]
    if gaps:
        lines += ["", "Coverage gaps (0 places found): " + "; ".join(gaps)]
    return "\n".join(lines)


def write_snapshot(rows, path):
    """Compact processed copy of the OSM places that the app can load at start-up (see app/osm_snapshot.py)."""
    payload = {
        "attribution": ATTRIBUTION,
        "generated": date.today().isoformat(),
        "count": len(rows),
        "places": sorted(rows, key=lambda r: (r["osm_id"] or "~", r["name"])),
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
