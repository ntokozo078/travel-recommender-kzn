"""Run the ETL pipeline: fetch Durban attractions from OpenStreetMap and load new ones.

    python main.py                              # fetch live from OpenStreetMap
    python main.py --from-file candidates.json  # reuse a saved download (offline)
"""
import argparse

import requests

from app import create_app
from etl_pipeline import pipeline

DEFAULT_CACHE_FILE = "durban_candidates.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--from-file", help="load candidates from this JSON file instead of calling the API")
    parser.add_argument("--save", default=DEFAULT_CACHE_FILE, help="where to save the raw download")
    args = parser.parse_args()

    if args.from_file:
        print(f"1/3 Extract: reading {args.from_file}")
        candidates = pipeline.load_candidates_file(args.from_file)
    else:
        print("1/3 Extract: querying OpenStreetMap (Overpass API)...")
        try:
            candidates = pipeline.extract()
        except requests.RequestException as exc:
            raise SystemExit(f"Extraction failed: {exc}\nTip: try again later or use --from-file.")
        pipeline.save_candidates_file(candidates, args.save)
        print(f"    saved raw download to {args.save}")
    print(f"    {len(candidates)} named features")

    print("2/3 Transform: cleaning and categorising...")
    rows = pipeline.transform(candidates)
    print(f"    {len(rows)} usable attractions")

    print("3/3 Load: writing to the database...")
    app = create_app()
    with app.app_context():
        inserted, skipped = pipeline.load(rows)
    print(f"Done. {inserted} new places added, {skipped} already existed.")


if __name__ == "__main__":
    main()
