"""One-off, idempotent data/schema steps. Each runs once per database and is recorded in schema_migrations.

Rules: never drop tables or columns, never delete rows. Only ADD columns / clear placeholder values.
"""
import logging

from sqlalchemy import inspect, text

from app import db
from app.models import SchemaMigration

log = logging.getLogger("ikhaya.migrations")

# Columns added to `places` after the first release: (name, portable SQL type).
NEW_PLACE_COLUMNS = [
    ("source", "VARCHAR(20)"),
    ("subcategory", "VARCHAR(40)"),
    ("region", "VARCHAR(40)"),
    ("website", "VARCHAR(300)"),
    ("phone", "VARCHAR(40)"),
    ("min_age", "INTEGER"),
    ("open_evening", "BOOLEAN"),
    ("open_late", "BOOLEAN"),
    ("opening_hours_raw", "VARCHAR(255)"),
    ("tags", "VARCHAR(255)"),
]


def _null_price_placeholders():
    """Early versions filled every place with price_tier "$$" as a default. That was a placeholder,
    not data, so clear it; real tiers come from data/place_overrides.json."""
    db.session.execute(text("UPDATE places SET price_tier = NULL WHERE price_tier = '$$'"))


def _add_place_columns():
    """ALTER TABLE ... ADD COLUMN for any column the model has but the table lacks (SQLite + PostgreSQL)."""
    existing = {col["name"] for col in inspect(db.engine).get_columns("places")}
    with db.engine.begin() as conn:
        for name, sql_type in NEW_PLACE_COLUMNS:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE places ADD COLUMN {name} {sql_type}"))
                log.info("added column places.%s", name)
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_places_region ON places (region)"))


def _add_osm_id_column():
    """osm_id lets the ETL update an OSM place in place instead of guessing by name."""
    existing = {col["name"] for col in inspect(db.engine).get_columns("places")}
    with db.engine.begin() as conn:
        if "osm_id" not in existing:
            conn.execute(text("ALTER TABLE places ADD COLUMN osm_id VARCHAR(30)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_places_osm_id ON places (osm_id)"))


def _clear_placeholder_osm_safety():
    """The old ETL stored safety_score 3.0 for every OSM place. No rating exists, so make it NULL
    ("not rated"). Curated places keep their values."""
    db.session.execute(text("UPDATE places SET safety_score = NULL WHERE source = 'osm' AND safety_score = 3.0"))


# (key, function), in order. Append new steps at the end; never edit or reorder existing ones.
MIGRATIONS = [
    ("20261123_clear_placeholder_price_tier", _null_price_placeholders),
    ("20261124_add_place_columns", _add_place_columns),
    ("20261124_clear_placeholder_osm_safety", _clear_placeholder_osm_safety),
    ("20261125_add_osm_id_column", _add_osm_id_column),
]


def run_migrations():
    done = {row.key for row in SchemaMigration.query.all()}
    for key, step in MIGRATIONS:
        if key in done:
            continue
        step()
        db.session.add(SchemaMigration(key=key))
        db.session.commit()
        log.info("applied migration %s", key)
