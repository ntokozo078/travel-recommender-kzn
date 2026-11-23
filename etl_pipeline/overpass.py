"""Polite Overpass API client: one request at a time, retries with backoff, results cached as JSON.

Never run requests in parallel and never loop on failure: each chunk gets at most
ATTEMPTS_PER_ENDPOINT tries on each of the public endpoints.
"""
import hashlib
import json
import re
import time
from pathlib import Path

import requests

from etl_pipeline.osm_mapping import QUERY_VALUES

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "iKhayaKZN/1.0 (KwaZulu-Natal heritage + trip planner; OSM data under ODbL)"
RETRYABLE_STATUS = {429, 502, 503, 504}
ATTEMPTS_PER_ENDPOINT = 2
MAX_BACKOFF = 120          # seconds


class OverpassError(RuntimeError):
    pass


def build_query(area_id, timeout=180, keys=()):
    """Named features in one boundary area: venues (amenity/leisure), karting, and tourism spots.

    `keys` limits the query to some OSM keys (used to split very large areas into smaller requests)."""
    parts = []
    for key, values in QUERY_VALUES.items():
        if keys and key not in keys:
            continue
        if key == "sport":
            parts.append(f'  nwr["sport"~"(^|;)karting(;|$)"]["name"](area.a);')
        else:
            parts.append(f'  nwr["{key}"~"^({"|".join(values)})$"]["name"](area.a);')
    body = "\n".join(parts)
    return f"[out:json][timeout:{timeout}];\narea({area_id})->.a;\n(\n{body}\n);\nout center tags;"


def _backoff(attempt, retry_after):
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), MAX_BACKOFF)
    return min(30 * (2 ** attempt), MAX_BACKOFF)


def fetch_elements(chunk, *, post=requests.post, sleep=time.sleep, urls=OVERPASS_URLS, log=print):
    """Return the raw Overpass elements for one chunk. Raises OverpassError after the last failure."""
    return fetch_query(build_query(chunk.area_id, keys=chunk.keys), chunk.name,
                       post=post, sleep=sleep, urls=urls, log=log)


def fetch_query(query, label, *, post=requests.post, sleep=time.sleep, urls=OVERPASS_URLS, log=print):
    """POST any Overpass query politely (retries with backoff on both endpoints) and return its elements."""
    last = None
    for url in urls:
        for attempt in range(ATTEMPTS_PER_ENDPOINT):
            try:
                resp = post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=(10, 200))
            except (requests.Timeout, requests.ConnectionError) as exc:
                last, retry_after = f"{type(exc).__name__}", None
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()["elements"]
                    except (ValueError, KeyError) as exc:
                        last, retry_after = f"bad response ({exc})", None
                elif resp.status_code in RETRYABLE_STATUS:
                    last, retry_after = f"HTTP {resp.status_code}", resp.headers.get("Retry-After")
                else:
                    raise OverpassError(f"{label}: HTTP {resp.status_code} (query rejected)")
            if attempt + 1 < ATTEMPTS_PER_ENDPOINT:
                wait = _backoff(attempt, retry_after)
                log(f"    {last} from {url}; waiting {wait}s before one retry")
                sleep(wait)
        log(f"    giving up on {url}: {last}")
    raise OverpassError(f"{label}: all endpoints failed ({last})")


# ---------------------------------------------------------------- cache (instance/cache/, git-ignored)
def cache_file(cache_dir, chunk):
    slug = re.sub(r"[^a-z0-9]+", "_", chunk.name.lower()).strip("_")
    return Path(cache_dir) / f"overpass_{slug}.json"


def query_hash(chunk):
    """Short fingerprint of the query a chunk sends, so a changed query never reuses old cached results."""
    return hashlib.sha1(build_query(chunk.area_id, keys=chunk.keys).encode()).hexdigest()[:12]


def read_cache(path, max_age_days, qhash=None):
    """Cached elements, or None when missing / unreadable / older than max_age_days (None = any age) /
    made by a different query (when qhash is given)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        elements = data["elements"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if max_age_days is not None and time.time() - data.get("fetched_at", 0) > max_age_days * 86400:
        return None
    if qhash and data.get("query_hash") != qhash:
        return None
    return elements


def write_cache(path, chunk, elements, qhash=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"chunk": chunk.name, "region": chunk.region, "fetched_at": time.time(), "query_hash": qhash, "elements": elements}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def extract_all(chunks, cache_dir, *, refresh=False, offline=False, max_age_days=7, pause=5.0,
                fetch=fetch_elements, sleep=time.sleep, log=print):
    """Elements for every chunk, tagged with `_region` (first chunk to claim a feature wins).

    Uses fresh cache files when present, so repeat runs make no requests. Returns (elements, failed_chunk_names).
    """
    claimed, elements, failed = {}, [], []
    fetched_any = False
    for chunk in chunks:
        path = cache_file(cache_dir, chunk)
        raw = None if refresh else read_cache(path, None if offline else max_age_days,
                                              None if offline else query_hash(chunk))
        source = "cache"
        if raw is None:
            if offline:
                log(f"  - {chunk.name}: no cache file, skipped (offline mode)")
                failed.append(chunk.name)
                continue
            if fetched_any:
                sleep(pause)                   # be polite: pause between requests
            log(f"  - {chunk.name}: asking Overpass...")
            try:
                raw = fetch(chunk, log=log)
            except OverpassError as exc:
                log(f"    FAILED: {exc}")
                failed.append(chunk.name)
                continue
            fetched_any = True
            write_cache(path, chunk, raw, query_hash(chunk))
            source = "Overpass"
        new = 0
        for el in raw:
            key = f"{el.get('type')}/{el.get('id')}"
            if key in claimed:
                continue
            claimed[key] = chunk.region
            el = dict(el, _region=chunk.region)
            elements.append(el)
            new += 1
        log(f"  - {chunk.name} ({chunk.region}): {len(raw)} features from {source}, {new} new")
        if not raw:
            log("    warning: 0 features. Check the boundary relation id in etl_pipeline/regions.py")
    return elements, failed
