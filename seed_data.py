"""Rebuild the places table from the curated list (this wipes existing rows, including ETL ones).

    python seed_data.py
"""
from app import create_app
from app.seed import reseed, build_places


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        reseed()
    print(f"Database reset with {len(build_places())} curated places.")
