# etl_pipeline/events_scraper.py
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pandas as pd

def scrape_events(url="https://visitdurban.travel/events/"):
    """
    Scrapes events from a target URL. 
    Returns a Pandas DataFrame of events.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    print(f"Starting scrape on {url}...")
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to retrieve site. Status code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.content, 'html.parser')
        events_list = []

        # NOTE: The selectors (div.event-card, h3.title) depend on the specific website's HTML.
        # You must Inspect Element on the real site to get the correct classes.
        # Below is a generic structure common in event sites.
        
        event_cards = soup.find_all('div', class_='event-item') 

        for card in event_cards:
            try:
                title = card.find('h3').text.strip()
                date_str = card.find('span', class_='date').text.strip()
                location = card.find('span', class_='location').text.strip()
                link = card.find('a')['href']
                
                # Basic cleaning of date
                # formatting usually requires specific parsing depending on the site (e.g., "12 Dec 2025")
                start_time = datetime.now() # Placeholder if parsing fails
                
                events_list.append({
                    "name": title,
                    "start_time": start_time,
                    "end_time": start_time, # Placeholder
                    "location_name": location,
                    "ticket_price": 0.0, # Default to free if not found
                    "event_url": link
                })
            except AttributeError:
                continue # Skip cards that are missing info

        print(f"Scraping complete. Found {len(events_list)} events.")
        return pd.DataFrame(events_list)

    except Exception as e:
        print(f"Error during scraping: {e}")
        return None

if __name__ == "__main__":
    # Test the scraper
    df = scrape_events()
    if df is not None:
        print(df.head())