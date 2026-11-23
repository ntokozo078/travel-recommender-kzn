# iKhaya KZN

One Flask app that combines two projects:

- **Heritage explorer**: Zulu clans and izithakazelo, herbs, foods, rituals, dance, dress, beads and cultural places.
- **Trip planner**: ranks KwaZulu-Natal places for today's weather, load-shedding status and (optionally) your location.

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
  __init__.py          app factory, creates and seeds the DB
  routes.py            pages + JSON API
  services.py          weather (Open-Meteo) and load-shedding context
  models.py, seed.py   Place model and the curated places
  templates/index.html single page shell
  static/css, static/js  the front end (hash-routed, no build step)
ml_engine/             scoring rules (weather, power, safety, distance)
etl_pipeline/          OpenStreetMap -> clean -> database
data/                  heritage JSON (served through /api/heritage/<section>)
main.py                run the ETL
seed_data.py           wipe and re-seed the database
setup_db.py            optional: create the PostgreSQL database
```

## API

| Route | Purpose |
|-------|---------|
| `GET /api/heritage/<section>` | `clans`, `herbs`, `foods`, `rituals`, `dance`, `dress`, `beads`, `places` |
| `GET /api/recommend` | `category`, `limit`, `indoor=1`, `lat`+`lon`, `min_safety`, `loadshedding=auto\|on\|off` |
| `GET /api/context` | current weather + power status |
| `GET /api/categories` | categories with place counts |
| `GET /api/heritage/clans/search?q=` | clan by surname or spelling (tolerant), "did you mean", praise-name reverse lookup |
| `GET /api/heritage/clans/suggest?q=` | autocomplete |
| `GET /api/heritage/clans/<surname>` | full clan record (base + enrichment, related clans as links) |
| `GET /api/places/near?lat=&lon=&limit=` | nearest places to a point (used for "near the clan's origin") |
| `POST /api/clan-corrections` | "Suggest a correction" (JSON; stored for review; 5 per hour per IP) |
| `GET /healthz` | health check |

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

### Tests

```
pip install pytest
python -m pytest
```

Tests use a temporary database and made-up clan data, so they never touch `instance/ikhaya.db`.

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

## Add more places (ETL)

```
python main.py                              # fetch Durban attractions from OpenStreetMap (no key needed)
python main.py --from-file durban_candidates.json   # reuse a saved download, works offline
```

It skips accommodation, de-duplicates by name and is safe to run repeatedly.

## PostgreSQL (optional)

```
copy .env.example .env      # then set DATABASE_URL
pip install psycopg2-binary
python setup_db.py
python run.py
```

Never commit `.env`. Load-shedding status is a simulated evening schedule (no Eskom feed is connected);
use the Auto / On / Off switch on the trip page to try both cases.
