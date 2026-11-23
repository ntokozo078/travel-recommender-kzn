from datetime import datetime, timezone

from app import db


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
    safety_score = db.Column(db.Float, default=3.0)
    price_tier = db.Column(db.String(10), default="$$")
    source = db.Column(db.String(20), default="curated")   # curated | osm
    last_updated = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "category": self.category,
            "address": self.address or "KwaZulu-Natal",
            "opening_hours": self.opening_hours or "Hours not listed",
            "image_url": self.image_url or "",
            "latitude": self.latitude,
            "longitude": self.longitude,
            "is_indoor": bool(self.is_indoor),
            "has_generator": bool(self.has_generator),
            "safety_score": self.safety_score,
            "price_tier": self.price_tier,
            "source": self.source,
        }


class ClanCorrection(db.Model):
    """A visitor's suggested correction for a clan record (reviewed by hand, never shown publicly)."""
    __tablename__ = "clan_corrections"

    id = db.Column(db.Integer, primary_key=True)
    surname = db.Column(db.String(100), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    contact = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
