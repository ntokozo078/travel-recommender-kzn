"""Application configuration. Secrets come from environment variables / a local .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _database_uri() -> str:
    """DATABASE_URL if set (Postgres etc.), otherwise a local SQLite file."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Heroku-style URLs use the legacy "postgres://" scheme which SQLAlchemy rejects.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    instance = BASE_DIR / "instance"
    instance.mkdir(exist_ok=True)
    return f"sqlite:///{(instance / 'ikhaya.db').as_posix()}"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DATA_DIR = BASE_DIR / "data"
    DEFAULT_LAT = -29.8587      # Durban
    DEFAULT_LON = 31.0218
    WEATHER_TIMEOUT = 4         # seconds
    WEATHER_CACHE_SECONDS = 600
