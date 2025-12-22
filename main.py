# etl_pipeline/main.py
from google_places_extract import fetch_places
from clean_data import clean_places_data
from load_to_db import load_places_to_db

# 1. Extract
raw_file = fetch_places("museum") 
# 2. Clean
cleaned_df = clean_places_data(raw_file)
# 3. Load
load_places_to_db(cleaned_df)