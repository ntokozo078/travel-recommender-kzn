# etl_pipeline/clean_data.py
import pandas as pd

def clean_places_data(raw_data_path):
    """
    Reads raw JSON data and cleans it for the database.
    Input: Path to raw JSON file.
    Output: Cleaned Pandas DataFrame.
    """
    try:
        # 1. Load Data
        df = pd.read_json(raw_data_path)
        
        # Check if 'results' key exists (common in Google API responses)
        if 'results' in df.columns:
            # Flatten the JSON if necessary
            # This depends on the exact structure of your raw file
            data_list = df['results'].tolist()
            df = pd.json_normalize(data_list)

        # 2. Rename Columns to match our Database Models
        # Google API gives 'name', 'vicinity', 'rating' -> We want 'name', 'description', 'safety_score'
        rename_map = {
            'vicinity': 'description',
            'rating': 'safety_score',
            'formatted_address': 'description'
        }
        df.rename(columns=rename_map, inplace=True)

        # 3. Handle Missing Values
        df['category'] = df['types'].apply(lambda x: x[0] if isinstance(x, list) and len(x) > 0 else 'General')
        df['safety_score'] = df['safety_score'].fillna(3.0) # Default neutral score
        df['price_tier'] = df.get('price_level', 2).apply(lambda x: '$' * int(x) if pd.notnull(x) else '$$')

        # 4. Context Logic (The "Data Engineering" Part)
        # Determine if indoor/outdoor based on category keywords
        def determine_indoor(category):
            indoor_keywords = ['museum', 'gallery', 'mall', 'bakery', 'restaurant', 'cinema']
            return any(keyword in str(category).lower() for keyword in indoor_keywords)

        df['is_indoor'] = df['category'].apply(determine_indoor)
        
        # Determine generator status (Randomized for MVP, or based on known list)
        # In a real app, you might merge this with a separate "Loadshedding Capable" CSV
        df['has_generator'] = False 

        # 5. Select only columns that exist in our DB model
        target_columns = ['name', 'description', 'category', 'latitude', 'longitude', 
                          'is_indoor', 'has_generator', 'safety_score', 'price_tier']
        
        # Ensure lat/lng exist (Google API usually puts them in geometry.location.lat)
        # If json_normalize was used, these might be 'geometry.location.lat'
        if 'geometry.location.lat' in df.columns:
            df['latitude'] = df['geometry.location.lat']
            df['longitude'] = df['geometry.location.lng']

        # Filter to only keep columns that are in our target list (and exist in df)
        final_cols = [c for c in target_columns if c in df.columns]
        cleaned_df = df[final_cols]

        print("Data Cleaning Complete.")
        return cleaned_df

    except Exception as e:
        print(f"Error cleaning data: {e}")
        return pd.DataFrame() # Return empty DF on failure