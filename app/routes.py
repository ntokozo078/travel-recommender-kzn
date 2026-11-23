"""All HTTP routes: the single-page site, the heritage JSON API and the recommender API."""
import json
import math
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlencode

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request
from sqlalchemy import func

from app import db
from app.models import ClanCorrection, Place
from app.services import ContextEngine
from ml_engine import recommend_places
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

CATEGORY_ORDER = ["Beach", "Nature", "Adventure", "Culture", "Food", "Shopping", "Entertainment"]


def _engine():
    if "engine" not in _context:
        cfg = current_app.config
        _context["engine"] = ContextEngine(cfg["WEATHER_TIMEOUT"], cfg["WEATHER_CACHE_SECONDS"])
    return _context["engine"]


def _load_json(filename):
    if filename not in _heritage_cache:
        path = current_app.config["DATA_DIR"] / filename
        with open(path, encoding="utf-8") as fh:
            _heritage_cache[filename] = json.load(fh)
    return _heritage_cache[filename]


def _float_arg(name, default, low, high):
    """Parse a float query arg, falling back to `default` if missing, invalid or out of range."""
    try:
        value = float(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


# ------------------------------------------------------------------ pages
@main.route("/")
def home():
    return render_template("index.html")


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

    ranked = sorted(
        ((haversine_km(lat, lon, p.latitude, p.longitude), p) for p in Place.query.all()),
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
    return jsonify(_engine().get_context(lat, lon, mode if mode in ("on", "off") else "auto"))


@main.route("/api/categories")
def categories():
    rows = dict(db.session.query(Place.category, func.count(Place.id)).group_by(Place.category).all())
    ordered = [c for c in CATEGORY_ORDER if c in rows] + sorted(c for c in rows if c not in CATEGORY_ORDER)
    return jsonify([{"name": c, "count": rows[c]} for c in ordered])


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

    query = Place.query
    if category and category != "All":
        query = query.filter_by(category=category)
    if indoor_only:
        query = query.filter_by(is_indoor=True)

    ctx = _engine().get_context(lat, lon, mode)
    prefs = {"min_safety": min_safety}
    if has_location:
        prefs.update(lat=lat, lon=lon)

    ranked = recommend_places(query.all(), prefs, ctx)
    return jsonify(
        context=ctx,
        category=category,
        total=len(ranked),
        results=ranked[:limit],
    )


@main.app_errorhandler(404)
def not_found(err):
    if request.path.startswith("/api/"):
        return jsonify(error=getattr(err, "description", "Not found")), 404
    return render_template("index.html"), 404
