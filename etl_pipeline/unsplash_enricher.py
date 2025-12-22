import requests
import os

# You need to register at https://unsplash.com/developers for a free key
# For MVP, you can hardcode it here or put it in .env
UNSPLASH_ACCESS_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')

def get_high_quality_image(query):
    """
    Searches Unsplash for a high-res, emotional image.
    """
    if not UNSPLASH_ACCESS_KEY:
        print("⚠️ No Unsplash Key found. Using placeholder.")
        return f"https://source.unsplash.com/800x600/?{query},durban"

    url = "https://api.unsplash.com/search/photos"
    params = {
        "query": f"{query} Durban", # e.g. "uShaka Marine World Durban"
        "per_page": 1,
        "orientation": "landscape",
        "client_id": UNSPLASH_ACCESS_KEY
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if data['results']:
            # Get the 'regular' size (good balance of quality/speed)
            return data['results'][0]['urls']['regular']
        else:
            # Fallback if specific search fails: Generic Category Search
            return get_generic_category_image(query)
    except Exception as e:
        print(f"Unsplash Error: {e}")
        return None

def get_generic_category_image(category):
    # Fallback to ensure we NEVER show a blank space
    return f"https://source.unsplash.com/800x600/?{category}"