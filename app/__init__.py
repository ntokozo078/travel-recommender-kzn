"""iKhaya KZN: Zulu heritage explorer + weather/power-aware KZN trip recommender."""
import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

db = SQLAlchemy()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Behind a reverse proxy (Render) the real client IP is in X-Forwarded-For; without this every
    # visitor looks like the proxy and shares one rate-limit bucket. Opt-in so it can't be spoofed locally.
    if os.environ.get("TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)

    # Clan records (base list + optional enrichment); problems are logged as warnings, never fatal.
    from app.clan_data import ClanStore
    data_dir = app.config["DATA_DIR"]
    app.extensions["clan_store"] = ClanStore(
        data_dir / "surnames.json", data_dir / "clans_enrichment.json"
    )

    from app.routes import main
    app.register_blueprint(main)

    with app.app_context():
        from app.migrations import run_migrations
        from app.overrides import apply_overrides
        from app.seed import seed_if_empty

        db.create_all()              # only creates missing tables, never drops anything
        run_migrations()
        seed_if_empty()
        if app.config.get("LOAD_OSM_SNAPSHOT"):
            from app.osm_snapshot import load_snapshot
            load_snapshot(app.config["DATA_DIR"] / "osm_places.json")
        apply_overrides(app.config["DATA_DIR"] / "place_overrides.json")

    return app
