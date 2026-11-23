"""Area awareness: turn a user-supplied SAPS crime-statistics file into data/safety_context.json.

Pure functions (no network, no database) so everything here is testable from small fixture files.

What this does and does not do:
  * It READS a file the user downloaded from SAPS themselves. Nothing is scraped and no figure is invented.
  * A SAPS station is only attached to a place on the map when its normalised name EXACTLY matches the name
    of an OpenStreetMap police station. No fuzzy guessing of coordinates; unmatched stations are reported.
  * The output holds raw reported counts per station. It is context, not a rating: it never feeds the
    recommender's score and never labels an area.

Expected CSV (UTF-8, header row, names case-insensitive):
    station    | police station | station name
    category   | crime category | crime
    count      | incidents | value   (long format: one row per station and category)
  or WIDE format, with one column per reporting period (e.g. "2023/2024" or "2023/24"): the latest period
  column is used. An optional `period` column is read in long format.
"""
import csv
import json
import re
from datetime import date
from pathlib import Path

from ml_engine.recommender import haversine_km

STATION_HEADERS = ("station", "police station", "station name", "policestation")
CATEGORY_HEADERS = ("category", "crime category", "crime", "crime_category")
COUNT_HEADERS = ("count", "incidents", "value", "total", "reported")
PERIOD_HEADERS = ("period", "year", "financial year")
PERIOD_COLUMN = re.compile(r"^(20\d{2})\s*[/\-_]\s*(\d{2}|\d{4})$")

# Categories kept by default: keyword match (case-insensitive) on the category name. Override with --categories.
DEFAULT_CATEGORY_KEYWORDS = ("robbery", "theft out of or from motor vehicle", "theft of motor vehicle", "burglary")
MAX_STATION_DISTANCE_KM = 15          # a place further than this from a matched station gets no area note

SOURCE_NAME = "South African Police Service (SAPS) crime statistics"
NOTE = ("Raw counts of incidents reported to this police station's precinct. They are not adjusted for population "
        "or visitors, say nothing about any one venue, and are not a safety rating.")


class SafetyDataError(ValueError):
    pass


def normalise_station(name):
    """'SAPS Durban Central Police Station' and 'Durban Central' -> 'durbancentral'."""
    text = str(name or "").lower()
    text = re.sub(r"south african police service|police station|police|saps|\bsap\b|\bstation\b|\bsps\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _pick(header, options):
    lowered = {h.strip().lower(): h for h in header}
    for option in options:
        if option in lowered:
            return lowered[option]
    return None


def _period_sort_key(label):
    match = PERIOD_COLUMN.match(label.strip())
    return int(match.group(1)) if match else -1


def _to_int(value):
    text = str(value).strip().replace(" ", "").replace(",", "")
    if not text or not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def read_saps_csv(path, keywords=DEFAULT_CATEGORY_KEYWORDS):
    """Return (period, {station name: {category: count}}) for the categories matching `keywords`.

    Rows with a missing or non-numeric count are skipped, never turned into zero."""
    keywords = tuple(k.lower() for k in keywords if k.strip())
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        station_col, category_col = _pick(header, STATION_HEADERS), _pick(header, CATEGORY_HEADERS)
        if not station_col or not category_col:
            raise SafetyDataError(f"{path}: need a station column and a category column (found: {', '.join(header)})")
        count_col, period_col = _pick(header, COUNT_HEADERS), _pick(header, PERIOD_HEADERS)
        year_cols = sorted((h for h in header if PERIOD_COLUMN.match(h.strip())), key=_period_sort_key)
        if not count_col and not year_cols:
            raise SafetyDataError(f"{path}: need a count column or a period column such as 2023/2024")
        wide_col = None if count_col else year_cols[-1]

        stations, periods = {}, set()
        for row in reader:
            station = " ".join(str(row.get(station_col) or "").split())
            category = " ".join(str(row.get(category_col) or "").split())
            if not station or not category or not any(k in category.lower() for k in keywords):
                continue
            count = _to_int(row.get(wide_col or count_col))
            if count is None:
                continue
            if period_col and row.get(period_col):
                periods.add(row[period_col].strip())
            stations.setdefault(station, {})
            stations[station][category] = stations[station].get(category, 0) + count
    period = wide_col.strip() if wide_col else (sorted(periods)[-1] if len(periods) == 1 else
                                                (" / ".join(sorted(periods)) if periods else None))
    return period, stations


def _police_points(elements):
    """OSM amenity=police elements -> {normalised name: (display name, lat, lon, osm_id)}. Ambiguous names are dropped."""
    found, ambiguous = {}, set()
    for el in elements:
        tags = el.get("tags") or {}
        name = " ".join(str(tags.get("name", "")).split())
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        key = normalise_station(name)
        if not key or lat is None or lon is None:
            continue
        if key in found and found[key][3] != f"{el.get('type')}/{el.get('id')}":
            ambiguous.add(key)
        found.setdefault(key, (name, float(lat), float(lon), f"{el.get('type')}/{el.get('id')}"))
    for key in ambiguous:
        del found[key]
    return found


def build_context(period, saps_stations, police_elements, *, source_file=None, today=None):
    """Join SAPS figures to OSM police stations by exact normalised name. Returns (context dict, unmatched names)."""
    points = _police_points(police_elements)
    stations, unmatched = [], []
    for saps_name, counts in sorted(saps_stations.items()):
        hit = points.get(normalise_station(saps_name))
        if not hit:
            unmatched.append(saps_name)
            continue
        name, lat, lon, osm_id = hit
        stations.append({
            "name": saps_name,
            "osm_name": name,
            "osm_id": osm_id,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "categories": dict(sorted(counts.items())),
        })
    context = {
        "source": SOURCE_NAME,
        "period": period,
        "generated": (today or date.today()).isoformat(),
        "source_file": Path(source_file).name if source_file else None,
        "note": NOTE,
        "stations": stations,
    }
    return context, unmatched


def write_context(context, path):
    Path(path).write_text(json.dumps(context, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- lookup used by the app
def load_context(path):
    """The parsed file, or None when it is missing, unreadable or malformed. The app works fine without it."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data.get("stations"), list):
            return None
        return data
    except (OSError, ValueError, AttributeError):
        return None


def area_awareness(context, lat, lon, max_km=MAX_STATION_DISTANCE_KM):
    """Neutral facts about the nearest matched police station, or None (no data / nothing close enough)."""
    if not context or lat is None or lon is None:
        return None
    best, best_km = None, None
    for station in context["stations"]:
        try:
            km = haversine_km(float(lat), float(lon), station["latitude"], station["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if best_km is None or km < best_km:
            best, best_km = station, km
    if best is None or best_km > max_km:
        return None
    return {
        "station": best["name"],
        "distance_km": round(best_km, 1),
        "period": context.get("period"),
        "source": context.get("source"),
        "categories": [{"category": c, "count": n} for c, n in best["categories"].items()],
        "note": context.get("note") or NOTE,
    }
