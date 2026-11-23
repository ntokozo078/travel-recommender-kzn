"""All HTTP routes: the single-page site, the heritage JSON API and the recommender API."""
import json
import math
import re
from datetime import date
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlencode

from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import ClanCorrection, Place
from app.services import FORECAST_DAYS, ContextEngine
from app.taxonomy import CATEGORIES, REGIONS, STAY, SUBCATEGORY_LABELS, is_valid_subcategory
from ml_engine import VIBES, category_cap, diversify, is_open_now, open_late_flag, recommend_places
from ml_engine.recommender import haversine_km

main = Blueprint("main", __name__)
_context = {}          # created lazily so it picks up app config
_heritage_cache = {}

# Heritage section -> (json file, key inside the file)
HERITAGE = {
    "herbs": ("herbs.json", "herbs"),
    "foods": ("food.json", "foods"),
    "places": ("places.json", "places"),
    "rituals": ("culture.json", "rituals"),
    "dance": ("culture.json", "dance"),
    "dress": ("culture.json", "dress"),
    "beads": ("culture.json", "beads"),
}

PRICE_TIERS = ["$", "$$", "$$$"]

# Shown in the <noscript> summary (the interactive site is built by JavaScript).
HERITAGE_SECTIONS = [
    {"id": "clans", "label": "Clans", "blurb": "Find your surname, izithakazelo and origins"},
    {"id": "herbs", "label": "Herbs", "blurb": "Medicinal plants of traditional healing"},
    {"id": "foods", "label": "Foods", "blurb": "Beloved dishes of the Zulu table"},
    {"id": "rituals", "label": "Rituals", "blurb": "Ceremonies that mark life's milestones"},
    {"id": "dance", "label": "Dance", "blurb": "Rhythm, song and celebration"},
    {"id": "dress", "label": "Dress", "blurb": "Attire that tells a story"},
    {"id": "beads", "label": "Beads", "blurb": "The colourful language of beadwork"},
    {"id": "places", "label": "Places", "blurb": "Sites preserving Zulu history"},
]
CATEGORY_ORDER = CATEGORIES


def _engine():
    if "engine" not in _context:
        cfg = current_app.config
        _context["engine"] = ContextEngine(cfg["WEATHER_TIMEOUT"], cfg["WEATHER_CACHE_SECONDS"])
    return _context["engine"]


def _load_json(filename):
    path = current_app.config["DATA_DIR"] / filename
    key = str(path)                                  # keyed by full path so different data folders never mix
    if key not in _heritage_cache:
        with open(path, encoding="utf-8") as fh:
            _heritage_cache[key] = json.load(fh)
    return _heritage_cache[key]


def _parse_date(raw, engine):
    """None when absent, an ISO date from today to FORECAST_DAYS - 1 days ahead, or False when invalid."""
    if not raw:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return False
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return False
    delta = (day - date.fromisoformat(engine.today())).days
    return raw if 0 <= delta < FORECAST_DAYS else False


def _float_arg(name, default, low, high):
    """Parse a float query arg, falling back to `default` if missing, invalid or out of range."""
    try:
        value = float(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


# ------------------------------------------------------------------ pages
def _page_context():
    """Facts for the server-rendered <noscript> summary. A missing table or file must never break the page."""
    context = {"heritage": HERITAGE_SECTIONS, "categories": [], "place_total": 0, "emergency": [], "info_note": ""}
    try:
        rows = dict(db.session.query(Place.category, func.count(Place.id)).group_by(Place.category).all())
        context["categories"] = [{"name": c, "count": rows[c], "is_stay": c == STAY} for c in CATEGORIES if c in rows]
        context["place_total"] = sum(n for c, n in rows.items() if c != STAY)
    except SQLAlchemyError:
        db.session.rollback()
    try:
        info = _load_json("info.json")
        section = next(sec for sec in info["sections"] if sec["id"] == "emergency")
        context["emergency"] = section.get("numbers", [])
        context["info_note"] = info.get("disclaimer", "")
    except (OSError, StopIteration, KeyError, ValueError):
        pass
    return context


@main.route("/")
def home():
    return render_template("index.html", **_page_context())


@main.route("/robots.txt")
def robots():
    body = f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {request.url_root}sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@main.route("/sitemap.xml")
def sitemap():
    """One URL: the app's views live behind the # of the address (#/info, #/trip ...), which search
    engines ignore, so they cannot be listed as separate pages."""
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"  <url><loc>{escape(request.url_root)}</loc></url>\n"
           "</urlset>\n")
    return Response(xml, mimetype="application/xml")


@main.route("/travel")
@main.route("/view_results")
def legacy_travel():
    """The original server-rendered recommender pages now live inside the single-page app."""
    category = request.args.get("category")
    suffix = "?" + urlencode({"category": category}) if category else ""
    return redirect(f"/#/trip{suffix}", code=302)


@main.route("/healthz")
def healthz():
    return jsonify(status="ok", places=Place.query.count())


# ------------------------------------------------------------------ heritage API
@main.route("/api/heritage/<section>")
def heritage(section):
    if section == "clans":
        return jsonify(_load_json("surnames.json"))
    if section not in HERITAGE:
        abort(404, description=f"Unknown heritage section '{section}'")
    filename, key = HERITAGE[section]
    return jsonify(_load_json(filename)[key])


# ------------------------------------------------------------------ travel info
@main.route("/api/info")
def info():
    """General practical information for visitors (data/info.json). Facts there are deliberately general."""
    try:
        return jsonify(_load_json("info.json"))
    except FileNotFoundError:
        abort(404, description="Travel info is not available")


# ------------------------------------------------------------------ clan explorer API
def _clans():
    return current_app.extensions["clan_store"]


@main.route("/api/heritage/clans/search")
def clan_search():
    return jsonify(_clans().search(request.args.get("q", "")))


@main.route("/api/heritage/clans/suggest")
def clan_suggest():
    try:
        limit = max(1, min(int(request.args.get("limit", 8)), 15))
    except ValueError:
        limit = 8
    q = request.args.get("q", "")
    return jsonify(query=q[:80], suggestions=_clans().suggest(q, limit))


@main.route("/api/heritage/clans/<path:surname>")
def clan_detail(surname):
    store = _clans()
    record = store.get(surname)
    if record is None:
        abort(404, description=f"No clan record for '{surname[:80]}'")
    return jsonify(store.full_record(record))


# Suggest-a-correction: stored for manual review. No login, so it is rate limited per IP and
# only accepts JSON (a cross-site HTML form cannot send that without a CORS preflight).
CORRECTION_LIMIT, CORRECTION_WINDOW = 5, 3600       # 5 per hour per IP
_correction_hits = defaultdict(deque)
_correction_lock = threading.Lock()


def _rate_limited(ip):
    now = time.time()
    with _correction_lock:
        hits = _correction_hits[ip]
        while hits and now - hits[0] > CORRECTION_WINDOW:
            hits.popleft()
        if len(hits) >= CORRECTION_LIMIT:
            return True
        hits.append(now)
        if len(_correction_hits) > 5000:             # keep memory bounded
            for key in [k for k, v in _correction_hits.items() if not v or now - v[-1] > CORRECTION_WINDOW]:
                del _correction_hits[key]
        return False


@main.route("/api/clan-corrections", methods=["POST"])
def clan_correction():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Please send JSON."), 415
    if data.get("website"):                          # honeypot: real visitors never fill this
        return jsonify(ok=True), 201
    message = str(data.get("message") or "").strip()
    contact = str(data.get("contact") or "").strip()[:120]
    record = _clans().get(str(data.get("surname") or ""))
    if record is None:
        return jsonify(error="Unknown clan."), 404
    if not 5 <= len(message) <= 1000:
        return jsonify(error="Please write between 5 and 1000 characters."), 400
    if _rate_limited(request.remote_addr or "?"):
        return jsonify(error="Too many suggestions from your connection. Please try again later."), 429
    db.session.add(ClanCorrection(surname=record["surname"], message=message, contact=contact or None))
    db.session.commit()
    return jsonify(ok=True), 201


@main.route("/api/places/near")
def places_near():
    """Read-only: the closest places to a point, nearest first."""
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify(error="lat and lon are required numbers"), 400
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify(error="lat/lon out of range"), 400
    try:
        limit = max(1, min(int(request.args.get("limit", 5)), 10))
    except ValueError:
        limit = 5

    query = Place.query
    if request.args.get("include_stays") not in ("1", "true", "on"):
        query = query.filter(Place.category != STAY)         # "near here" means things to see, not hotels
    ranked = sorted(
        ((haversine_km(lat, lon, p.latitude, p.longitude), p) for p in query.all()),
        key=lambda pair: pair[0],
    )[:limit]
    return jsonify(results=[
        {**p.to_dict(), "distance_km": round(d, 1)} for d, p in ranked
    ])


# ------------------------------------------------------------------ recommender API
@main.route("/api/context")
def context():
    cfg = current_app.config
    lat = _float_arg("lat", cfg["DEFAULT_LAT"], -90, 90)
    lon = _float_arg("lon", cfg["DEFAULT_LON"], -180, 180)
    mode = request.args.get("loadshedding", "auto")
    at = request.args.get("at")
    if at and not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", at):
        return jsonify(error="at must be a time like 21:30 (South African time)"), 400
    return jsonify(_engine().get_context(lat, lon, mode if mode in ("on", "off") else "auto", at=at or None))


def _parse_price(raw):
    """None if absent, 1-3 for a valid tier, False if invalid."""
    if raw in (None, "", "any"):
        return None
    tier = {"1": 1, "2": 2, "3": 3, "$": 1, "$$": 2, "$$$": 3}.get(raw.strip())
    return tier or False


@main.route("/api/filters")
def filters():
    """What the planner's filter controls can offer, based on data we actually have."""
    prices = dict(db.session.query(Place.price_tier, func.count(Place.id))
                  .filter(Place.price_tier.isnot(None)).group_by(Place.price_tier).all())
    subs = {}
    for category, slug, n in (db.session.query(Place.category, Place.subcategory, func.count(Place.id))
                              .filter(Place.subcategory.isnot(None)).group_by(Place.category, Place.subcategory).all()):
        subs.setdefault(category, []).append({"slug": slug, "label": SUBCATEGORY_LABELS.get(slug, slug), "count": n})
    order = list(SUBCATEGORY_LABELS)
    for items in subs.values():
        items.sort(key=lambda i: order.index(i["slug"]) if i["slug"] in order else 999)
    regions = dict(db.session.query(Place.region, func.count(Place.id)).filter(Place.region.isnot(None)).group_by(Place.region).all())
    return jsonify(
        prices={tier: prices.get(tier, 0) for tier in PRICE_TIERS},
        subcategories=subs,
        regions=[{"name": r, "count": regions[r]} for r in REGIONS if r in regions],
    )


@main.route("/api/forecast")
def forecast():
    """The next 7 days of weather for a point, for the planner's date picker."""
    cfg = current_app.config
    lat = _float_arg("lat", cfg["DEFAULT_LAT"], -90, 90)
    lon = _float_arg("lon", cfg["DEFAULT_LON"], -180, 180)
    engine = _engine()
    return jsonify(today=engine.today(), **engine.get_forecast(lat, lon))


@main.route("/api/categories")
def categories():
    rows = dict(db.session.query(Place.category, func.count(Place.id)).group_by(Place.category).all())
    ordered = [c for c in CATEGORY_ORDER if c in rows] + sorted(c for c in rows if c not in CATEGORY_ORDER)
    return jsonify([{"name": c, "count": rows[c], "in_all": c != STAY} for c in ordered])


@main.route("/api/recommend")
@main.route("/recommend")
def recommend_api():
    cfg = current_app.config
    has_location = "lat" in request.args and "lon" in request.args
    lat = _float_arg("lat", cfg["DEFAULT_LAT"], -90, 90)
    lon = _float_arg("lon", cfg["DEFAULT_LON"], -180, 180)

    category = request.args.get("category", "All")
    mode = request.args.get("loadshedding", "auto")
    mode = mode if mode in ("on", "off") else "auto"
    indoor_only = request.args.get("indoor") in ("1", "true", "on")
    try:
        limit = max(1, min(int(request.args.get("limit", 12)), 50))
    except ValueError:
        limit = 12
    min_safety = _float_arg("min_safety", 0, 0, 5) or None
    at = request.args.get("at")
    if at and not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", at):
        return jsonify(error="at must be a time like 21:30 (South African time)"), 400
    engine = _engine()
    on = _parse_date(request.args.get("date"), engine)
    if on is False:
        return jsonify(error=f"date must be YYYY-MM-DD, from today up to {FORECAST_DAYS - 1} days ahead"), 400
    vibes = [v.strip().lower() for v in request.args.get("vibe", "").split(",") if v.strip()]
    if any(v not in VIBES for v in vibes) or len(vibes) > 3:
        return jsonify(error=f"vibe must be up to 3 of: {', '.join(VIBES)}"), 400
    tourist = request.args.get("tourist") in ("1", "true", "on")
    subcategory = request.args.get("subcategory") or None
    if subcategory and not is_valid_subcategory(subcategory):
        return jsonify(error="unknown subcategory"), 400
    region = request.args.get("region") or None
    if region and region not in REGIONS:
        return jsonify(error=f"region must be one of: {', '.join(REGIONS)}"), 400
    open_now = request.args.get("open_now") in ("1", "true", "on")
    open_late = request.args.get("open_late") in ("1", "true", "on")
    want_points = request.args.get("points") in ("1", "true", "on")
    max_price = _parse_price(request.args.get("price"))
    if max_price is False:
        return jsonify(error="price must be one of $, $$, $$$ (or 1, 2, 3)"), 400

    query = Place.query
    if category and category != "All":
        query = query.filter_by(category=category)
    if category in (None, "", "All"):
        query = query.filter(Place.category != STAY)      # places to sleep are not "things to do"
    if indoor_only:
        query = query.filter_by(is_indoor=True)
    if max_price:                       # "up to" this tier; places with no known price are excluded
        query = query.filter(Place.price_tier.in_(PRICE_TIERS[:max_price]))
    if subcategory:
        query = query.filter_by(subcategory=subcategory)
    if region:
        query = query.filter_by(region=region)

    ctx = engine.get_context(lat, lon, mode, at=at or None, on=on)
    prefs = {"min_safety": min_safety, "vibes": vibes}
    if has_location:
        prefs.update(lat=lat, lon=lon)

    places = query.all()
    # Hours filters keep only places whose listed hours prove it; unknown hours are never assumed.
    if open_late:
        places = [p for p in places if open_late_flag(p) is True]
    if open_now:
        places = [p for p in places if is_open_now(p, ctx["time"]) is True]

    # Sea conditions for beaches on the chosen day (today when no date was asked for); missing data is simply left out.
    prefs["marine"] = engine.marine_for_places(places, ctx["time"]["date"])

    ranked = recommend_places(places, prefs, ctx)
    # Tourist mode: no single category may fill the top results (only meaningful across all categories).
    mix = tourist and category in (None, "", "All")
    results = diversify(ranked, limit) if mix else ranked[:limit]
    return jsonify(
        context=ctx,
        category=category,
        vibes=vibes,
        tourist_mode={"enabled": bool(mix), "cap_per_category": category_cap(limit) if mix else None},
        total=len(ranked),
        results=results,
        # every matching place, for the map (clusters) even when the list only shows the first page
        points=[{"id": r["id"], "name": r["name"], "category": r["category"],
                 "latitude": r["latitude"], "longitude": r["longitude"]} for r in ranked] if want_points else None,
    )


@main.app_errorhandler(404)
def not_found(err):
    if request.path.startswith("/api/"):
        return jsonify(error=getattr(err, "description", "Not found")), 404
    return render_template("index.html", **_page_context()), 404
