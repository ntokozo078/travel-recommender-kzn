# iKhaya KZN

One Flask app that combines two projects:

- **Heritage explorer**: Zulu clans and izithakazelo, herbs, foods, rituals, dance, dress, beads and cultural places.
- **Trip planner**: ranks KwaZulu-Natal places for the weather, time of day, load-shedding status and (optionally) your
  location, with nightlife, entertainment, places to stay, a 7-day forecast and a printable itinerary.

## Run it

```
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:5001 (set `PORT` to change it). The SQLite database is created and seeded
automatically in `instance/ikhaya.db`, so nothing else needs installing.

## Layout

```
run.py                 start the server
config.py              settings (reads .env)
app/
  __init__.py          app factory: creates tables, runs migrations, seeds, loads the OSM snapshot
  routes.py            pages (+ robots.txt, sitemap.xml) and the JSON API
  services.py          weather, 7-day forecast, sea conditions, load-shedding (all with fallbacks)
  models.py, seed.py   Place model and the curated places
  migrations.py        additive, recorded start-up migrations (never drops anything)
  taxonomy.py          categories, subcategories, regions
  overrides.py         data/place_overrides.json (hand-maintained prices, hours, ratings)
  clan_data.py         clan records and search
  templates/index.html page shell, meta tags and the <noscript> summary
  static/css, static/js  the front end (hash-routed, no build step)
ml_engine/             explainable scoring rules (weather, time of day, power, safety, waves, vibes)
etl_pipeline/          OpenStreetMap -> clean -> database (overpass, osm_mapping, pipeline, loader, regions)
data/                  heritage JSON, info.json, clan enrichment, osm_places.json (the ETL snapshot)
scripts/               check_images.py (reports broken image links)
tests/                 pytest suite (temporary databases, no network)
.github/workflows/     CI: runs pytest on every push
main.py                run the ETL
seed_data.py           wipe and re-seed the database
setup_db.py            optional: create the PostgreSQL database
```

## API

| Route | Purpose |
|-------|---------|
| `GET /api/heritage/<section>` | `clans`, `herbs`, `foods`, `rituals`, `dance`, `dress`, `beads`, `places` |
| `GET /api/recommend` | `category`, `limit`, `indoor=1`, `price=$\|$$\|$$$` (up to this tier; unknown prices excluded), `vibe=nightlife\|family\|nature\|culture\|food\|budget` (up to 3, comma-separated), `tourist=1` (mix categories), `at=HH:MM` (what-if time, South African time), `date=YYYY-MM-DD` (rank for that day's forecast, today to 6 days ahead), `subcategory=`, `region=`, `open_now=1`, `open_late=1`, `points=1` (all matches for the map), `lat`+`lon`, `min_safety`, `loadshedding=auto\|on\|off` |
| `GET /api/forecast?lat=&lon=` | the next 7 days of weather for a point (the planner's date picker) |
| `GET /api/info` | practical travel info for visitors (`data/info.json`) |
| `GET /api/filters` | filter values the data supports, with counts: price tiers, subcategories per category, regions |
| `GET /api/context` | current weather + power status |
| `GET /api/categories` | categories with place counts |
| `GET /api/heritage/clans/search?q=` | clan by surname or spelling (tolerant), "did you mean", praise-name reverse lookup |
| `GET /api/heritage/clans/suggest?q=` | autocomplete |
| `GET /api/heritage/clans/<surname>` | full clan record (base + enrichment, related clans as links) |
| `GET /api/places/near?lat=&lon=&limit=` | nearest places to a point (used for "near the clan's origin"); hotels are left out unless `include_stays=1` |
| `POST /api/clan-corrections` | "Suggest a correction" (JSON; stored for review; 5 per hour per IP) |
| `GET /healthz` | health check |
| `GET /robots.txt`, `GET /sitemap.xml` | for search engines (see "Search engines and sharing") |

`/travel` and `/view_results` redirect to the Plan a trip page for old links.

## Clan explorer: adding or editing a clan entry

Two files, two jobs:

- `data/surnames.json` is the base list (surname, praise names, one-line origin). Don't reformat it.
- `data/clans_enrichment.json` is the optional extra detail, keyed by surname. This is the file you edit.

To add detail for a clan, add (or fill in) its entry. The key must match a surname in `surnames.json`
(case and accents don't matter). **Every field is optional: leave it `null` unless you have a source.**
Wrong heritage data is worse than missing data, and the page hides anything that is empty.

```json
"Surname": {
  "alt_spellings": ["Other spelling"],
  "izithakazelo_notes": [{ "name": "Praise name", "note": "What it refers to" }],
  "meaning": null,
  "ancestor": null,
  "origin": { "summary": null, "region": null, "lat": null, "lng": null, "migration_note": null },
  "related_clans": ["Another Surname"],
  "taboos_or_totem": null,
  "notable_people": ["Name"],
  "today_found_in": ["Place"],
  "sources": ["Book, author, year", "https://link"],
  "confidence": "oral-tradition"
}
```

| Field | Notes |
|-------|-------|
| `confidence` | `verified` (needs at least one source), `oral-tradition` or `unverified` |
| `origin.lat` / `origin.lng` | decimal degrees, both or neither; enables the map pin and "Places near the clan's origin" |
| `alt_spellings` | searchable; also tried for spelling tolerance (Ntombela / Ntombella already match) |
| `related_clans` | must be surnames in `surnames.json`; shown as clickable links |

The app checks the file when it starts and prints a `clan data:` warning for unknown fields, bad
coordinates, wrong value types, `verified` without sources, unknown related clans and so on. A bad value is
ignored; it never stops the app. The three entries shipped in the file are empty format demos.

Corrections sent from the page are saved in the `clan_corrections` table (surname, message, optional
contact). Read them with any SQLite viewer, or `ClanCorrection.query.all()` in a Flask shell. Note that
`python seed_data.py` drops every table, including this one.

### Tests and CI

```
pip install pytest
python -m pytest
```

Tests use a temporary database and made-up data, and they never touch the network or `instance/ikhaya.db`
(a guard makes any outside call fail like an outage, so the fallbacks are tested too). They cover the
recommender rules, the API shapes, the ETL mapping from a fixture file, and upgrading the oldest database schema
without losing data. `.github/workflows/tests.yml` runs the suite on every push and pull request.

## Deploy (Render)

Web service, Python runtime:

| Setting | Value |
|---------|-------|
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn run:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT` |
| Health check path | `/healthz` |
| Environment | `SECRET_KEY` (any long random string), `TRUST_PROXY=1` |

Keep `--workers 1`: the SQLite database seeds itself on first start and the correction rate limit is
kept in memory. Render's free-tier disk is ephemeral, so stored corrections are lost on each redeploy;
set `DATABASE_URL` to a Render PostgreSQL database (and add `psycopg2-binary` to requirements) to keep them.

## Travel info and places to stay

- **`#/info`** has emergency numbers (112, 10111 and the public ambulance number 10177), getting around,
  money and tipping, SIM cards and data, etiquette and cultural respect, and load-shedding and water-outage
  tips. The text lives in `data/info.json`. It is deliberately general: no prices and no other phone numbers,
  and anything that can vary says "check locally" (a test enforces this). Edit the file to change the page.
- **Stay** is a category for hotels, guest houses, hostels, chalets and camp sites from OpenStreetMap.
  It is kept out of the "All" ranking (a hotel is not a thing to do), and choosing it shows the places
  grouped by region. Prices, availability and facilities are not listed. Every other card has a
  "Find stays near here" link: a plain Google Maps search, with no scraping and no affiliate links.
- After changing which OSM tags the ETL pulls, run `python main.py --write-snapshot` again. Cached Overpass
  results made by an older query are detected and refetched automatically.

## Forecast, sea conditions and your trip

- **Pick a date:** a seven-day strip in the planner (Open-Meteo forecast, cached like current weather).
  Choosing a day ranks places for that day's forecast and weekday (so "Open now" uses that day's opening
  hours, at noon unless you set a time under More filters). If the forecast service is down the strip says so
  and places are ranked for today.
- **Waves:** beaches show the forecast wave height from Open-Meteo's marine data (half-degree grid, cached an
  hour, left alone for five minutes after a failure). Waves of 2.5 m or more cost 3 points and say so; smaller
  waves are information only. Inland or unavailable data simply shows nothing.
- **My trip (`#/itinerary`):** press **＋ Trip** on any card. Places are grouped by day, can be reordered or moved
  between days, and are saved in this browser only (localStorage). Set the first day to see each day's
  forecast. Distances between stops are straight-line estimates and are labelled "approximate": there is no routing
  service, so they are not driving distances or times. The Print button gives a clean printable page.

## The trip planner

- Category chips (including Nightlife and Entertainment) with a subcategory row for those two, a region
  filter, Indoor only, **Open now** and **Open late**, Budget, a vibe, "Mix categories" (tourist mode) and a
  what-if time of day. Options only appear when the data has something for them.
- **Open now / Open late only show places whose listed hours prove it.** A place with no hours listed is
  left out rather than assumed open, so these filters can look short while OpenStreetMap's hours are sparse.
- Cards show the type of place, opening hours, minimum age, website and phone only when known; places with no
  safety rating say "Not safety-rated" (that is not a verdict either way).
- Nightlife results show general safety tips (licensed e-hailing or a pre-booked ride, never drink and drive,
  keep valuables out of sight, go in a group, check hours) and "Many venues are 18+. Bring ID." They are
  general advice, not claims about any venue.
- The map shows every match, with numbered pins for the places in the list and clusters
  ([Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) from a CDN) when it is crowded.
- Everything that comes from the database or OpenStreetMap is escaped before it is shown.

## How places are ranked

Rule-based and explainable: every point added or removed shows up as a chip on the card with its points,
and `score` is exactly the sum of the chips. Unknown facts (no safety rating, no hours, no price) never
add or remove points.

| Rule | Points |
|------|--------|
| Rain: indoor / outdoor | +5 / -3 |
| Dry daytime, outdoor place | +3 (no sunshine bonus after dark) |
| Load-shedding (simulated): has a generator / not | +5 / -5 |
| Evening (17:30 to 04:00 South African time): Nightlife | +6 |
| Evening entertainment: hours show it is open in the evening / a cinema, theatre, casino, comedy, music or events venue with no hours listed | +4 / +2 |
| Evening: Beach, Nature, Adventure | -4 |
| Daytime: Nightlife not listed as open now | -4 |
| Listed hours say open now / closed now | +2 / -6 |
| Curator safety rating (0-5): `(rating - 3) x 2`, times 1.5 in the evening; **not rated = no points** | varies |
| Distance from you (only when you share a location) | up to -6 |
| `vibe=`: matching category or subcategory, price for `budget`, "often 18+" for `family` | see `ml_engine/recommender.py` |

`tourist=1` (with category "All") keeps one category from filling the top results: at most a quarter of the
list (3 of 12, 1 of 3) per category. `at=21:30` previews another time of day for today.

## Place facts: prices, hours, safety ratings

Prices are never guessed: a place shows a price tier only when one is known. To add facts you can
source, edit `data/place_overrides.json` (keyed by exact place name):

```json
{ "Place Name": { "price_tier": "$$", "safety_score": 4.2, "opening_hours": "09:00 - 17:00" } }
```

Other fields you can set the same way: `subcategory`, `region`, `website`, `phone`, `min_age`,
`open_evening`, `open_late`, `opening_hours_raw`, `tags`. Unknown is always `null` and is never shown.

- **Categories:** Beach, Nature, Adventure, Culture, Food, Shopping, Entertainment, Nightlife
  (list and subcategories in `app/taxonomy.py`; subcategories are stored as slugs such as `nightclub`).
- **Regions:** Durban, North Coast, South Coast, Midlands, Drakensberg, Zululand, Pietermaritzburg, Other KZN.
- **Safety:** `safety_score` is a 0-5 rating you supply. `null` means "not rated": it adds or removes no points
  and is never treated as neutral or unsafe. The app shows tips and ratings, never a verdict.
- **Upgrading an existing database:** on start-up the app adds any missing columns
  (`app/migrations.py`, `ALTER TABLE ... ADD COLUMN`). It never drops tables or deletes rows, and each
  step is recorded in `schema_migrations` so it runs once.

It is applied at every start and is safe to re-run. Invalid values are ignored with a warning in the log.

Power status ("load-shedding") is **simulated** (18:00-20:59 South African time); the planner says so
next to it. Dead image links can be listed with `python scripts/check_images.py [--heritage]`
(read-only; it changes nothing).

## Add more places (ETL: all of KwaZulu-Natal)

```
python main.py                              # use cached results younger than 7 days, fetch the rest
python main.py --regions Durban,Midlands    # only some regions (or chunk names)
python main.py --refresh                    # ignore the cache and ask Overpass again
python main.py --offline                    # cache only, no network
python main.py --dry-run                    # print the summary, change nothing
python main.py --write-snapshot             # also write data/osm_places.json (see below)
python main.py --from-file FILE             # a saved cache file, or the old durban_candidates.json
```

- **Source:** OpenStreetMap through the public Overpass API (no key). The province is covered by
  querying each district boundary in turn (`etl_pipeline/regions.py`, which also maps districts to
  your regions, so edit it there). One request at a time, a User-Agent, retries with backoff, and a
  pause between requests. Raw results are cached in `instance/cache/` (git-ignored), so re-runs make
  no requests while the cache is fresh.
- **What it pulls:** amenity nightclub, bar, pub, cinema, theatre, casino, arts_centre, events_venue,
  biergarten; leisure bowling_alley, ice_rink, amusement_arcade, miniature_golf, water_park,
  trampoline_park, escape_game, dance; tourism theme_park, zoo, aquarium, attraction (plus museum and
  gallery, kept from the first version); sport=karting. Unnamed features and accommodation are skipped.
- **What it stores:** category and subcategory from the tags (`etl_pipeline/osm_mapping.py`), the
  original opening-hours text, website, phone and `min_age` when tagged, and `open_evening` /
  `open_late` only when the hours text proves them (otherwise unknown). Safety and price are never set.
- **Safe to repeat:** places are matched by OSM id, then by name within 150 m. Re-running never
  duplicates, and curated places are never changed. It prints a summary by region and category so you
  can see coverage gaps.
- **Deployed copy:** hosts with a throw-away disk start empty, so a complete run is saved with
  `--write-snapshot` as `data/osm_places.json` and loaded at start-up (`LOAD_OSM_SNAPSHOT=0` turns
  that off). It is only written from a full run of every chunk.

## Data sources and limits

| What | Where it comes from | Limits |
|------|--------------------|--------|
| Heritage content | `data/*.json` (herbs, foods, culture, places, surnames) | Public-heritage summaries. Clan histories vary between families and regions; unknown detail is left empty, never guessed. |
| Curated places | `app/seed.py` | 36 hand-picked places. Safety ratings are the curator's own (not rated = no rating); prices are unknown until set in `data/place_overrides.json`. Some image links are dead (`scripts/check_images.py` lists them) and show a placeholder. |
| Other places | [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, via the Overpass API, under the [ODbL](https://opendatacommons.org/licenses/odbl/) | Volunteer-made: venues can be missing, closed or out of date, coverage varies by town, and opening hours, websites and phone numbers are often absent. `data/osm_places.json` is a derived database and stays under the ODbL. The footer credits OpenStreetMap. |
| Weather, 7-day forecast, waves | [Open-Meteo](https://open-meteo.com/) (no key). Sea data only exists for coastal points. | Forecasts are forecasts. If the service is down the app says so and ranks for today with an estimate. |
| Load-shedding | **Simulated** (a made-up evening schedule), labelled wherever it is shown | No live Eskom feed is connected. |
| Travel info | `data/info.json` | General facts only, no prices or other phone numbers; anything that can vary says "check locally". Not official advice. |
| Distances in "My trip" | Straight-line (great circle) | Approximate and labelled so: not driving distances or times. |
| Region grouping | `etl_pipeline/regions.py` | A district-level approximation (e.g. "Drakensberg" is two whole districts). Edit it to change the grouping. |

The app shows tips and ratings, never a verdict that a venue or area is safe or unsafe.

## Search engines and sharing

- Every view sets its own page title and description as you move around, and the page carries Open Graph tags,
  a canonical link, `robots.txt` and `sitemap.xml`. Without JavaScript, a server-rendered summary
  (heritage sections, place counts, emergency numbers) is shown instead of an empty page.
- **Limit:** the app's views live after the `#` in the address (`#/info`, `#/trip`...). Search engines and link
  scrapers ignore that part, so they see one page, and the sitemap lists one URL. Indexing each view separately
  would need path URLs (`/info`, `/trip`) instead of `#`, which would change the URL scheme.
- There is no preview image yet (`og:image`).

## PostgreSQL (optional)

```
copy .env.example .env      # then set DATABASE_URL
pip install psycopg2-binary
python setup_db.py
python run.py
```

Never commit `.env`. Load-shedding status is a simulated evening schedule (no Eskom feed is connected);
use the Auto / On / Off switch on the trip page to try both cases.
