"""Build data/safety_context.json from a SAPS crime-statistics file you downloaded yourself.

    python scripts/build_safety_context.py                      # newest .csv in data/raw/
    python scripts/build_safety_context.py --input data/raw/saps_2024.csv
    python scripts/build_safety_context.py --police-file FILE   # saved Overpass result instead of asking Overpass
    python scripts/build_safety_context.py --categories robbery,burglary

Nothing is scraped. Police station positions come from OpenStreetMap (one polite Overpass request, cached in
instance/cache/). A SAPS station is kept only when its name matches an OSM police station exactly (after
removing words like "police station"); the others are listed so you can check them by hand.
See etl_pipeline/safety.py for the expected CSV layout.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from etl_pipeline import overpass, safety  # noqa: E402

POLICE_QUERY = ('[out:json][timeout:120];\narea["ISO3166-2"="ZA-KZN"]->.a;\n'
                'nwr["amenity"="police"]["name"](area.a);\nout center tags;')
CACHE = ROOT / "instance" / "cache" / "overpass_police.json"
DEFAULT_OUTPUT = ROOT / "data" / "safety_context.json"


def police_elements(args):
    if args.police_file:
        data = json.loads(Path(args.police_file).read_text(encoding="utf-8"))
        return data["elements"] if isinstance(data, dict) else data
    if CACHE.exists() and not args.refresh and time.time() - CACHE.stat().st_mtime < 30 * 86400:
        return json.loads(CACHE.read_text(encoding="utf-8"))["elements"]
    print("Asking Overpass for KwaZulu-Natal police stations (one request)...")
    elements = overpass.fetch_query(POLICE_QUERY, "KZN police stations")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"fetched_at": time.time(), "elements": elements}), encoding="utf-8")
    return elements


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--input", help="the SAPS CSV (default: newest .csv in data/raw/)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--police-file", help="a saved Overpass result with amenity=police elements")
    parser.add_argument("--categories", default=",".join(safety.DEFAULT_CATEGORY_KEYWORDS),
                        help="comma-separated keywords; a crime category is kept when its name contains one")
    parser.add_argument("--refresh", action="store_true", help="ignore the cached police station list")
    args = parser.parse_args(argv)

    source = Path(args.input) if args.input else None
    if source is None:
        files = sorted((ROOT / "data" / "raw").glob("*.csv"), key=lambda p: p.stat().st_mtime) \
            if (ROOT / "data" / "raw").is_dir() else []
        if not files:
            sys.exit("No SAPS file found. Download the station crime statistics from the SAPS website, save them as a "
                     "CSV in data/raw/, and run this again. (Nothing is made up when the file is missing.)")
        source = files[-1]
    if not source.exists():
        sys.exit(f"File not found: {source}")

    keywords = [k.strip() for k in args.categories.split(",") if k.strip()]
    period, saps = safety.read_saps_csv(source, keywords)
    if not saps:
        sys.exit(f"No rows in {source.name} matched the categories: {', '.join(keywords)}")
    print(f"Read {len(saps)} SAPS stations from {source.name} (period: {period or 'unknown'}).")

    context, unmatched = safety.build_context(period, saps, police_elements(args), source_file=source)
    safety.write_context(context, args.output)
    print(f"Matched {len(context['stations'])} stations to OpenStreetMap police stations -> {args.output}")
    if unmatched:
        print(f"{len(unmatched)} not matched (left out, never guessed): " + "; ".join(unmatched[:40])
              + (" ..." if len(unmatched) > 40 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
