import os
from urllib.parse import quote_plus

class Config:
    SECRET_KEY = 'dev-key-12345'
    db_pass = quote_plus("Ntokozo@02")
    
    # 2. We force the app to use 127.0.0.1 (IPv4) instead of localhost
    SQLALCHEMY_DATABASE_URI = f"postgresql://postgres:{db_pass}@127.0.0.1:5432/travel_db"
    # ------------------------------------------
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Free API Configuration (No keys needed)
    UNSPLASH_ACCESS_KEY = None
    GOOGLE_PLACES_KEY = None
    OPENWEATHER_KEY = None
    