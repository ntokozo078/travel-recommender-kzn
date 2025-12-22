# etl_pipeline/google_places_extract.py
import requests
import json
import os
import time

# NOTE: You need a GOOGLE_PLACES_KEY in your .env file for this to work.
API_KEY = os.environ.get('GOOGLE_PLACES_KEY')
DURBAN_LAT = "-29.8587"
DURBAN_LON = "31.0218"

def fetch_places(keyword="tourist attraction"):
    """
    Extracts raw data from Google Places API
    """
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        'location': f"{DURBAN_LAT},{DURBAN_LON}",
        'radius': 10000, # 10km radius
        'keyword': keyword,
        'key': API_KEY
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        # Save Raw Data (Data Lake approach)
        filename = f"etl_pipeline/raw_data_{keyword.replace(' ', '_')}.json"
        with open(filename, 'w') as f:
            json.dump(data, f)
            
        print(f"Extraction Complete: Saved {len(data.get('results', []))} items to {filename}")
        return filename
        
    except Exception as e:
        print(f"Error extracting data: {e}")
        return None

if __name__ == "__main__":
    fetch_places("museum")