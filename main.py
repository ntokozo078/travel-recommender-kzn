"""Run the OpenStreetMap ETL for all of KwaZulu-Natal.

    python main.py                          # use cached results younger than 7 days, fetch the rest
    python main.py --regions Durban,Midlands  # only these regions (or chunk names)
    python main.py --refresh                # ignore the cache and ask Overpass again
    python main.py --offline                # cache only, never touch the network
    python main.py --from-file FILE         # a saved cache file or the old durban_candidates.json
    python main.py --dry-run                # show the summary, write nothing to the database
    python main.py --write-snapshot         # also write data/osm_places.json (what the deployed app loads)

Raw Overpass results are cached in instance/cache/ (git-ignored). One request at a time, with pauses.
Re-running is safe: no duplicates, and curated places are never changed.
"""
import argparse
import sys
from pathlib import Path

from etl_pipeline import overpass, pipeline, regions

ROOT = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT = ROOT / "data" / "osm_places.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--regions", default="", help="comma-separated region or chunk names (default: all)")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache")
    parser.add_argument("--offline", action="store_true", help="use cache files only")
    parser.add_argument("--from-file", help="load features from this JSON file instead of Overpass")
    parser.add_argument("--max-age-days", type=float, default=7, help="reuse cache files younger than this")
    parser.add_argument("--pause", type=float, default=5.0, help="seconds to wait between Overpass requests")
    parser.add_argument("--dry-run", action="store_true", help="do not write to the database")
    parser.add_argument("--write-snapshot", nargs="?", const=str(DEFAULT_SNAPSHOT), metavar="PATH",
                        help="write the processed rows to a JSON snapshot (default data/osm_places.json)")
    args = parser.parse_args(argv)

    failed, subset = [], False
    if args.from_file:
        print(f"1/3 Extract: reading {args.from_file}")
        elements = pipeline.load_candidates_file(args.from_file)
        subset = True                                   # a single file is never the whole province
    else:
        wanted = [r for r in args.regions.split(",") if r.strip()]
        chunks = regions.chunks_for_regions(wanted)
        if not chunks:
            sys.exit(f"No chunks match {args.regions!r}. Known regions: "
                     + ", ".join(sorted({c.region for c in regions.CHUNKS})))
        subset = len(chunks) != len(regions.CHUNKS)
        print(f"1/3 Extract: {len(chunks)} chunk(s) from OpenStreetMap (Overpass), cache in instance/cache/")
        elements, failed = overpass.extract_all(
            chunks, ROOT / "instance" / "cache", refresh=args.refresh, offline=args.offline,
            max_age_days=args.max_age_days, pause=args.pause)
    print(f"    {len(elements)} named features")

    print("2/3 Transform: mapping tags, cleaning, de-duplicating...")
    rows = pipeline.transform(elements)
    print(f"    {len(rows)} places\n")
    print(pipeline.summarize(rows))
    if failed:
        print(f"\nWARNING: no data for {', '.join(failed)} (run again later; finished chunks are cached).")

    if args.write_snapshot:
        if subset or failed:
            print("\nSnapshot NOT written: it must come from a complete run of every chunk.")
        else:
            pipeline.write_snapshot(rows, args.write_snapshot)
            print(f"\nSnapshot written to {args.write_snapshot}")

    if args.dry_run:
        print("\nDry run: database untouched.")
        return 1 if failed else 0

    print("\n3/3 Load: updating the database...")
    from app import create_app
    from etl_pipeline.loader import load_rows

    app = create_app()
    with app.app_context():
        stats = load_rows(rows)
    print("    " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in stats.items()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
