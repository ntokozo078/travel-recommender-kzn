"""Report broken image URLs. Read-only: it never edits or replaces anything.

    python scripts/check_images.py                 # images of places in the database
    python scripts/check_images.py --heritage      # also the images in data/*.json
    python scripts/check_images.py --strict        # exit 1 if any are broken (for CI)

Requests go out one at a time with a short pause, so image hosts are not hammered.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

USER_AGENT = "iKhayaKZN-image-check/1.0"


def check(url, timeout=10):
    """Return (ok, detail) for one image URL."""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code in (403, 405, 501):            # some hosts refuse HEAD
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
            resp.close()
        kind = resp.headers.get("Content-Type", "")
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        if kind and not kind.lower().startswith("image/"):
            return False, f"not an image ({kind.split(';')[0]})"
        return True, f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        return False, type(exc).__name__


def place_images():
    from app import create_app
    from app.models import Place

    app = create_app()
    with app.app_context():
        return [(f"place: {p.name}", p.image_url) for p in Place.query.order_by(Place.name) if p.image_url]


def heritage_images():
    found = []
    for path in sorted((ROOT / "data").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if isinstance(node.get("image"), str) and node["image"].startswith("http"):
                    found.append((f"{path.name}: {node.get('name', '?')}", node["image"]))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--heritage", action="store_true", help="also check images in data/*.json")
    parser.add_argument("--strict", action="store_true", help="exit with status 1 if any image is broken")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds to wait between requests")
    args = parser.parse_args()

    items = place_images() + (heritage_images() if args.heritage else [])
    seen, broken = {}, []
    for label, url in items:
        if url not in seen:
            seen[url] = check(url)
            time.sleep(args.delay)
        ok, detail = seen[url]
        if not ok:
            broken.append((label, url, detail))

    for label, url, detail in broken:
        print(f"BROKEN  {detail:<18} {label}\n        {url}")
    print(f"\nChecked {len(items)} images ({len(seen)} unique URLs): {len(broken)} broken.")
    if broken:
        print("Nothing was changed. Replace the URLs by hand (seed.py, data/*.json or place_overrides).")
    return 1 if (broken and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
