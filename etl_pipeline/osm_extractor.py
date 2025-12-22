import requests
import json
import os

def fetch_durban_attractions():
    """
    Uses OpenStreetMap (Overpass API) to fetch tourist sites in Durban.
    Free. No Auth. Raw Data.
    """
    # Public Overpass API endpoint
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    # Query: Get nodes/ways/relations with 'tourism' tag in Durban area
    # BBox: South=-30.0, West=30.8, North=-29.7, East=31.1
    overpass_query = """
    [out:json];
    (
      node["tourism"](-30.0, 30.8, -29.7, 31.1);
      way["tourism"](-30.0, 30.8, -29.7, 31.1);
      relation["tourism"](-30.0, 30.8, -29.7, 31.1);
    );
    out center;
    """
    
    print("🌍 Connecting to OpenStreetMap (Overpass API)...")
    try:
        response = requests.get(overpass_url, params={'data': overpass_query})
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            return []
            
        data = response.json()
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return []
    
    raw_places = data.get('elements', [])
    print(f"📦 Raw Data Received: {len(raw_places)} items")
    
    # --- CLEANUP PHASE ---
    clean_list = []
    
    # Words to ignore to filter out 'trash'
    ignored_words = ['guest house', 'backpackers', 'bnb', 'lodge', 'hotel', 'chalet']
    
    for item in raw_places:
        tags = item.get('tags', {})
        name = tags.get('name')
        
        # 1. MUST have a name
        if not name: 
            continue
            
        # 2. Filter out accommodation (we want experiences, not beds)
        # Check if any ignored word is in the name (case insensitive)
        if any(word in name.lower() for word in ignored_words):
            continue
            
        # 3. Get generic category
        category = tags.get('tourism', 'Attraction').capitalize()
        
        # 4. Extract Location
        lat = item.get('lat') or item.get('center', {}).get('lat')
        lon = item.get('lon') or item.get('center', {}).get('lon')

        place = {
            'name': name,
            'category': category,
            'latitude': lat,
            'longitude': lon,
            'address': tags.get('addr:street', 'Durban, KZN'),
            'opening_hours': tags.get('opening_hours', '09:00 - 17:00') 
        }
        clean_list.append(place)

    print(f"💎 Filtered Candidates: {len(clean_list)} potential spots.")
    
    # Save to main folder
    output_file = 'durban_candidates.json'
    with open(output_file, 'w') as f:
        json.dump(clean_list, f, indent=4)
    
    print(f"✅ Saved to '{output_file}'. Open it and choose your Top 20!")

if __name__ == "__main__":
    fetch_durban_attractions()