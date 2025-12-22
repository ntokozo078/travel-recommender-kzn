# app/routes.py
from flask import Blueprint, render_template, request, jsonify
from app.models import Place
from app.services import ContextEngine
from ml_engine import recommend_places

main = Blueprint('main', __name__)
context_engine = ContextEngine()

@main.route('/')
def home():
    # This renders the beautiful Landing Page (index.html)
    return render_template('index.html')

# app/routes.py (Updated Filter Logic)
@main.route('/view_results', methods=['GET'])
def view_results():
    # 1. Capture User Inputs
    try:
        user_lat = float(request.args.get('lat', -29.8587))
        user_lon = float(request.args.get('lon', 31.0218))
    except ValueError:
        user_lat = -29.8587
        user_lon = 31.0218

    category = request.args.get('category')

    # 2. Get Context (Weather/Power)
    weather = context_engine.get_current_weather(user_lat, user_lon)
    is_loadshedding = context_engine.check_loadshedding("area_id")
    context_data = {'weather': weather, 'loadshedding': is_loadshedding}

    # 3. DATABASE FILTERING (The Fix)
    # If a category is selected, ONLY get places from that category.
    if category and category != "All":
        all_places = Place.query.filter_by(category=category).all()
    else:
        all_places = Place.query.all()
    
    # 4. Apply AI Sorting (Ranking the filtered list)
    user_prefs = {'category': category, 'min_safety': 3.0}
    recs = recommend_places(all_places, user_prefs, context_data)

    return render_template('results.html', recommendations=recs, context=context_data)

# Keep the API endpoint for your Portfolio testing
@main.route('/recommend', methods=['GET'])
def recommend_api():
    # ... (Keep your existing API logic here if you want, or just rely on the UI)
    return "API Endpoint active. Use the website home page."