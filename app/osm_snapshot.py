"""Load the processed OpenStreetMap snapshot (data/osm_places.json) at start-up.

Hosts with a throw-away disk (Render's free tier) start with an empty database every time, so the
ETL's results are committed as a compact snapshot and loaded here. The load is an idempotent upsert:
re-running never duplicates anything and never changes a curated place.

Regenerate the snapshot with:  python main.py --write-snapshot
"""
import json
import logging
from pathlib import Path

log = logging.getLogger("ikhaya.osm")


def load_snapshot(path):
    """Upsert the snapshot's places. Returns the stats dict, or None when there is nothing to load."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))["places"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("OSM snapshot %s is unreadable (%s); skipped", path.name, exc)
        return None

    from etl_pipeline.loader import load_rows

    stats = load_rows(rows)
    log.info("OSM snapshot: %s", stats)
    return stats
