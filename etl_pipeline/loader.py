"""Idempotent load of OSM rows into the places table.

Rules: running it again never creates duplicates, and it NEVER changes a curated place
(source != "osm"). OSM rows are machine-owned, so they are refreshed from the newest data.
"""
from app import db
from app.models import Place
from app.taxonomy import CATEGORIES, REGIONS, is_valid_subcategory
from etl_pipeline.pipeline import ProximityIndex

# Fields refreshed on existing OSM rows. image_url, safety_score and price_tier are never touched:
# OSM has no values for them, and hand-made overrides must survive.
REFRESHED = ("name", "description", "category", "subcategory", "region", "address", "opening_hours",
             "opening_hours_raw", "website", "phone", "min_age", "open_evening", "open_late", "tags",
             "latitude", "longitude", "is_indoor")


def _valid(row):
    try:
        return (
            row.get("name") and -90 <= float(row["latitude"]) <= 90 and -180 <= float(row["longitude"]) <= 180
            and row.get("category") in CATEGORIES
            and (row.get("region") is None or row["region"] in REGIONS)
            and (row.get("subcategory") is None or is_valid_subcategory(row["subcategory"]))
        )
    except (KeyError, TypeError, ValueError):
        return False


def load_rows(rows):
    """Upsert rows. Returns {"inserted", "updated", "unchanged", "skipped_existing", "invalid"}."""
    stats = dict(inserted=0, updated=0, unchanged=0, skipped_existing=0, invalid=0)
    places = Place.query.all()
    by_osm_id = {p.osm_id: p for p in places if p.osm_id}
    index = ProximityIndex()
    for p in places:
        index.add(p.name, p.latitude, p.longitude, p)

    for row in rows:
        if not _valid(row):
            stats["invalid"] += 1
            continue

        target = by_osm_id.get(row.get("osm_id")) if row.get("osm_id") else None
        if target is None:
            match = index.find(row["name"], row["latitude"], row["longitude"])
            if match is not None and match.source != "osm":
                stats["skipped_existing"] += 1          # a curated place already covers this venue
                continue
            target = match                              # an older OSM row (maybe from the previous ETL): adopt it

        if target is not None and target.source != "osm":
            stats["skipped_existing"] += 1
            continue

        if target is None:
            place = Place(**{k: v for k, v in row.items() if hasattr(Place, k)})
            place.source = "osm"
            db.session.add(place)
            index.add(place.name, place.latitude, place.longitude, place)
            if place.osm_id:
                by_osm_id[place.osm_id] = place
            stats["inserted"] += 1
            continue

        changed = False
        if row.get("osm_id") and target.osm_id != row["osm_id"]:
            target.osm_id = row["osm_id"]
            changed = True
        for field in REFRESHED:
            if getattr(target, field) != row.get(field):
                setattr(target, field, row.get(field))
                changed = True
        stats["updated" if changed else "unchanged"] += 1

    db.session.commit()
    return stats
