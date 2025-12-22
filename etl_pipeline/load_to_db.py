# etl_pipeline/load_to_db.py
import os
from sqlalchemy import create_engine
import pandas as pd

# Load Database URL from .env or config
# Ensure your .env file has DATABASE_URL=postgresql://user:password@localhost/travel_db
DB_URI = os.environ.get('DATABASE_URL') or 'postgresql://postgres:password@localhost/travel_db'

def load_places_to_db(cleaned_df):
    """
    Takes a cleaned Pandas DataFrame and loads it into PostgreSQL.
    """
    if cleaned_df.empty:
        print("No data to load.")
        return

    try:
        print("Connecting to Database...")
        engine = create_engine(DB_URI)
        connection = engine.connect()

        # Load data to 'places' table
        # if_exists='append': Adds to existing data
        # if_exists='replace': Wipes table and adds new data (Good for development)
        cleaned_df.to_sql('places', con=engine, if_exists='append', index=False, method='multi')
        
        print(f"Successfully loaded {len(cleaned_df)} records into the database.")
        connection.close()

    except Exception as e:
        print(f"Failed to load data to DB: {e}")

if __name__ == "__main__":
    # For testing: create a dummy DF and try to load it
    data = {
        'name': ['Test Place'],
        'description': ['A test description'],
        'category': ['Test'],
        'latitude': [-29.0],
        'longitude': [31.0],
        'is_indoor': [True],
        'has_generator': [True],
        'safety_score': [5.0],
        'price_tier': ['$$']
    }
    df = pd.DataFrame(data)
    load_places_to_db(df)