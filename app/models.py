from datetime import datetime, timezone

from app import db
from app.taxonomy import subcategory_label


class Place(db.Model):
    __tablename__ = "places"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), index=True)
    address = db.Column(db.String(200))
    opening_hours = db.Column(db.String(100))
    image_url = db.Column(db.String(500))

    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    is_indoor = db.Column(db.Boolean, default=False)
    has_generator = db.Column(db.Boolean, default=False)
    safety_score = db.Column(db.Float)                  # 0-5; NULL = not rated (never a neutral default)
    price_tier = db.Column(db.String(10))            # "$" | "$$" | "$$$"; NULL = unknown
    source = db.Column(db.String(20), default="curated")   # curated | osm
    osm_id = db.Column(db.String(30), index=True)       # "node/123"; lets the ETL refresh a row in place

    # Entertainment / nightlife detail. Every field is optional: NULL means unknown and is never shown.
    subcategory = db.Column(db.String(40))              # slug from app/taxonomy.py, e.g. "nightclub"
    region = db.Column(db.String(40), index=True)       # one of taxonomy.REGIONS
    website = db.Column(db.String(300))
    phone = db.Column(db.String(40))
    min_age = db.Column(db.Integer)
    open_evening = db.Column(db.Boolean)                # NULL = unknown (not False)
    open_late = db.Column(db.Boolean)                   # NULL = unknown (not False)
    opening_hours_raw = db.Column(db.String(255))       # original OSM opening_hours text
    tags = db.Column(db.String(255))                    # comma-separated
    last_updated = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "category": self.category,
            "address": self.address,
            "opening_hours": self.opening_hours,
            "image_url": self.image_url or "",
            "latitude": self.latitude,
            "longitude": self.longitude,
            "is_indoor": bool(self.is_indoor),
            "has_generator": bool(self.has_generator),
            "safety_score": self.safety_score,
            "price_tier": self.price_tier,
            "source": self.source,
            "safety_rated": self.safety_score is not None,
            "subcategory": self.subcategory,
            "subcategory_label": subcategory_label(self.subcategory),
            "region": self.region,
            "website": self.website,
            "phone": self.phone,
            "min_age": self.min_age,
            "open_evening": self.open_evening,
            "open_late": self.open_late,
            "opening_hours_raw": self.opening_hours_raw,
            "tags": [t.strip() for t in (self.tags or "").split(",") if t.strip()],
        }


class ClanCorrection(db.Model):
    """A visitor's suggested correction for a clan record (reviewed by hand, never shown publicly)."""
    __tablename__ = "clan_corrections"

    id = db.Column(db.Integer, primary_key=True)
    surname = db.Column(db.String(100), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    contact = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class SchemaMigration(db.Model):
    """Records which one-off data/schema steps in app/migrations.py have run."""
    __tablename__ = "schema_migrations"

    key = db.Column(db.String(100), primary_key=True)
    applied_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
