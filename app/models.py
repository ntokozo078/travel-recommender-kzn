# app/models.py
from app import db
from datetime import datetime

class Place(db.Model):
    __tablename__ = 'places'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))
    
    # New Fields for "Real" feel
    address = db.Column(db.String(200))          # e.g. "1 King Shaka Ave, Durban"
    opening_hours = db.Column(db.String(100))    # e.g. "09:00 - 17:00"
    image_url = db.Column(db.String(500))        # Link to a REAL photo
    
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    is_indoor = db.Column(db.Boolean, default=False)
    has_generator = db.Column(db.Boolean, default=False)
    safety_score = db.Column(db.Float)
    price_tier = db.Column(db.String(10))
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'address': self.address,
            'opening_hours': self.opening_hours,
            'image_url': self.image_url,
            'is_indoor': self.is_indoor,
            'has_generator': self.has_generator
        }