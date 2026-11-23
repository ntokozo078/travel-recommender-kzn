"""Test fixtures: every test gets its own temp database and its own small, made-up clan data.

The made-up names below are test fixtures only. They carry no heritage claims.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app, db          # noqa: E402
from config import Config               # noqa: E402

GENERIC = "Historical origins tied to the KwaZulu-Natal region."

FIXTURE_CLANS = {"clans": [
    {"surname": "Ntombela", "praise_poetry": "Alpha, Beta", "origins": GENERIC},
    {"surname": "Kheswa", "praise_poetry": "Gamma, Beta", "origins": GENERIC},
    {"surname": "Lamula", "praise_poetry": "Beta", "origins": GENERIC},
    {"surname": "Ndlovu", "praise_poetry": "Delta, Epsilon", "origins": "Test origin text."},
    {"surname": "Buthelezi", "praise_poetry": "Zeta", "origins": GENERIC},
    {"surname": "Zulu", "praise_poetry": "Eta", "origins": GENERIC},
]}

# Dummy enrichment for Ndlovu only (Zulu, Ntombela... stay un-enriched for the fallback tests).
FIXTURE_ENRICHMENT = {
    "_format": "ignored note",
    "Ndlovu": {
        "alt_spellings": ["Ndhlovu"],
        "izithakazelo_notes": [{"name": "Delta", "note": "DUMMY note"}],
        "meaning": "DUMMY meaning",
        "origin": {"summary": "DUMMY", "region": "DUMMY", "lat": -29.0, "lng": 31.0, "migration_note": None},
        "related_clans": ["Zulu", "Missing Clan"],
        "sources": ["DUMMY source"],
        "confidence": "oral-tradition",
    },
}


def write_data(directory, clans=FIXTURE_CLANS, enrichment=FIXTURE_ENRICHMENT):
    directory.mkdir(exist_ok=True)
    (directory / "surnames.json").write_text(json.dumps(clans), encoding="utf-8")
    if enrichment is not None:
        (directory / "clans_enrichment.json").write_text(json.dumps(enrichment), encoding="utf-8")
    return directory


def make_app(tmp_path, data_dir, **overrides):
    class TestConfig(Config):
        TESTING = True
        LOAD_OSM_SNAPSHOT = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
        DATA_DIR = data_dir

    for key, value in overrides.items():
        setattr(TestConfig, key, value)

    import app.routes as routes
    routes._correction_hits.clear()          # fresh rate-limit state per test
    return create_app(TestConfig)


@pytest.fixture
def data_dir(tmp_path):
    return write_data(tmp_path / "data")


@pytest.fixture
def app(tmp_path, data_dir):
    application = make_app(tmp_path, data_dir)
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def real_client(tmp_path):
    """App using the repo's real data/ folder (for 'old endpoint unchanged' checks)."""
    application = make_app(tmp_path, ROOT / "data")
    yield application.test_client()
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never touch the network: outside calls fail like an outage and the app must fall back."""
    import requests

    def blocked(*args, **kwargs):
        raise requests.ConnectionError("network is disabled in tests")

    monkeypatch.setattr(requests, "get", blocked)
    import app.routes as routes
    routes._context.clear()                # a fresh ContextEngine (caches, marine cool-down) per test
