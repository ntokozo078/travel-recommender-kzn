import requests
from datetime import datetime

class ContextEngine:
    def get_current_weather(self, lat, lon):
        """
        Fetches weather from Open-Meteo (No API Key required).
        """
        try:
            # Open-Meteo Free API Endpoint
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true"
            }
            
            response = requests.get(url, params=params)
            data = response.json()
            
            # Extract weather code
            if 'current_weather' in data:
                weather_code = data['current_weather']['weathercode']
                temp = data['current_weather']['temperature']
                
                # Convert numeric code to text
                condition = self._interpret_weather_code(weather_code)
                return f"{condition} ({temp}°C)"
            
            return "Clear (25°C)" # Fallback

        except Exception as e:
            print(f"Weather API Error: {e}")
            return "Clear (25°C)" # Default if internet fails

    def _interpret_weather_code(self, code):
        """
        Translates Open-Meteo codes to human text.
        """
        if code == 0: return "Clear Sky"
        if code in [1, 2, 3]: return "Partly Cloudy"
        if code in [45, 48]: return "Foggy"
        if code in [51, 53, 55]: return "Drizzle"
        if code in [61, 63, 65]: return "Rainy"
        if code in [80, 81, 82]: return "Heavy Rain"
        if code >= 95: return "Thunderstorm"
        return "Clear"

    def check_loadshedding(self, area_id):
        """
        Simulates Loadshedding status (ESKOM API is paid/complex).
        For MVP, we base this on the current hour.
        """
        current_hour = datetime.now().hour
        # Simulate loadshedding between 6PM and 8PM
        if 18 <= current_hour <= 20:
            return True
        return False