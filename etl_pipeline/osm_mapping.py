"""Pure functions: turn OpenStreetMap tags into our category / subcategory / hours / contact fields.

Nothing here touches the network or the database, so it is fully testable from fixture data.
Unknown always stays None; we never fill a gap with a guess.
"""
import re

# Priority order when an element carries several of these keys.
KEY_PRIORITY = ("amenity", "leisure", "sport", "tourism")

# (key, value) -> (category, subcategory slug or None, indoor?)
# is_indoor is a heuristic from the venue type (it feeds the weather rules), not a surveyed fact.
RULES = {
    ("amenity", "nightclub"): ("Nightlife", "nightclub", True),
    ("amenity", "bar"): ("Nightlife", "bar", True),
    ("amenity", "pub"): ("Nightlife", "pub", True),
    ("amenity", "biergarten"): ("Nightlife", "pub", False),
    ("amenity", "cinema"): ("Entertainment", "cinema", True),
    ("amenity", "theatre"): ("Entertainment", "theatre", True),
    ("amenity", "casino"): ("Entertainment", "casino", True),
    ("amenity", "events_venue"): ("Entertainment", "events_venue", True),
    ("amenity", "arts_centre"): ("Culture", None, True),
    ("leisure", "bowling_alley"): ("Entertainment", "bowling", True),
    ("leisure", "ice_rink"): ("Entertainment", "ice_skating", True),
    ("leisure", "amusement_arcade"): ("Entertainment", "arcade", True),
    ("leisure", "miniature_golf"): ("Entertainment", "mini_golf", False),
    ("leisure", "water_park"): ("Entertainment", "water_park", False),
    ("leisure", "trampoline_park"): ("Entertainment", None, True),
    ("leisure", "escape_game"): ("Entertainment", None, True),
    ("leisure", "dance"): ("Entertainment", None, True),
    ("sport", "karting"): ("Entertainment", "go_karting", False),
    ("tourism", "theme_park"): ("Entertainment", "amusement_park", False),
    ("tourism", "zoo"): ("Nature", None, False),
    ("tourism", "aquarium"): ("Entertainment", None, True),
    ("tourism", "attraction"): ("Entertainment", None, False),
    # Places to sleep (their own category, region-grouped in the app):
    ("tourism", "hotel"): ("Stay", "hotel", True),
    ("tourism", "guest_house"): ("Stay", "guest_house", True),
    ("tourism", "hostel"): ("Stay", "hostel", True),
    ("tourism", "chalet"): ("Stay", "chalet", True),
    ("tourism", "camp_site"): ("Stay", "camp_site", False),
    # Kept from the first version of the ETL so culture venues don't disappear:
    ("tourism", "museum"): ("Culture", None, True),
    ("tourism", "gallery"): ("Culture", None, True),
}

# Overpass filters, built from RULES so the query and the mapping can never drift apart.
QUERY_VALUES = {}
for (_key, _value) in RULES:
    QUERY_VALUES.setdefault(_key, []).append(_value)

# tourism=* values for lodging we still skip (the five wanted kinds are in RULES above as "Stay").
ACCOMMODATION = {"apartment", "caravan_site", "motel", "alpine_hut", "wilderness_hut", "camp_pitch"}
STAY_TOURISM = {"hotel", "guest_house", "hostel", "chalet", "camp_site"}

_NIGHTLIFE_NAME_HINTS = (
    (re.compile(r"shisa\s*-?\s*nyama|shisanyama", re.I), "shisa_nyama"),
    (re.compile(r"\blounge\b", re.I), "lounge"),
    (re.compile(r"tap\s*room|taproom|brewery|brewing|brewhouse", re.I), "brewery_taproom"),
)
_COMEDY = re.compile(r"\bcomedy\b", re.I)
_GENERIC_ATTRACTION_HINTS = (          # only used for the vague tourism=attraction tag
    (re.compile(r"beach|bay\b|lagoon|pier", re.I), ("Beach", None, False)),
    (re.compile(r"park|garden|reserve|forest|trail|nature|falls|gorge", re.I), ("Nature", None, False)),
    (re.compile(r"museum|gallery|memorial|heritage|monument|battlefield", re.I), ("Culture", None, True)),
)


def classify(tags):
    """Return (category, subcategory, is_indoor, source_tag) for an OSM tag dict, or None to skip it."""
    if tags.get("tourism") in ACCOMMODATION:
        return None
    if tags.get("tourism") in STAY_TOURISM:             # a hotel that also has a bar is still a hotel
        category, sub, indoor = RULES[("tourism", tags["tourism"])]
        return category, sub, indoor, f"tourism={tags['tourism']}"
    for key in KEY_PRIORITY:
        values = [v.strip() for v in str(tags.get(key, "")).split(";")]
        for value in values:
            rule = RULES.get((key, value))
            if rule:
                category, sub, indoor = rule
                name = tags.get("name", "")
                if category == "Nightlife" and sub in ("bar", "pub"):
                    for pattern, hinted in _NIGHTLIFE_NAME_HINTS:
                        if pattern.search(name):
                            sub = hinted
                            break
                elif category == "Entertainment" and sub in ("theatre", "events_venue", "cinema") and _COMEDY.search(name):
                    sub = "comedy"
                elif (key, value) == ("tourism", "attraction"):
                    for pattern, hinted in _GENERIC_ATTRACTION_HINTS:
                        if pattern.search(name):
                            category, sub, indoor = hinted
                            break
                return category, sub, indoor, f"{key}={value}"
    return None


# ---------------------------------------------------------------- opening hours
_DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)"
_DAY_SPEC = re.compile(rf"^{_DAY}(?:\s*-\s*{_DAY})?(?:\s*,\s*{_DAY}(?:\s*-\s*{_DAY})?)*\s*")
_TIME_RANGE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
EVENING_START, EVENING_END = 18 * 60, 23 * 60   # "open evening" = open at some point 18:00-23:00 on at least one day
LATE_AFTER = 23 * 60        # "open late" = still open after 23:00 on at least one day


ALWAYS_OPEN = ("24/7", "24 hours", "24 hrs", "24hrs", "24 hour")
_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def _expand_days(spec):
    """'Mo-Fr, Su' -> {0,1,2,3,4,6}. Public-holiday tokens (PH, SH) can't be evaluated, so they are ignored."""
    days = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = (x.strip() for x in part.split("-", 1))
            if a in _WEEKDAYS and b in _WEEKDAYS:
                k, end = _WEEKDAYS.index(a), _WEEKDAYS.index(b)
                while True:
                    days.add(k)
                    if k == end:
                        break
                    k = (k + 1) % 7
        elif part in _WEEKDAYS:
            days.add(_WEEKDAYS.index(part))
    return days


def _weekly_schedule(raw):
    """Parse into ({weekday: [(start_min, end_min)]}, fully_understood). Later rules override earlier ones
    for the same days (OSM semantics). Returns None when there is nothing usable."""
    schedule, understood, any_rule = {}, True, False
    for rule in (r.strip() for r in raw.split(";")):
        if not rule:
            continue
        any_rule = True
        match = _DAY_SPEC.match(rule)
        days = _expand_days(rule[:match.end()]) if match else set(range(7))
        rest = rule[match.end():].strip() if match else rule
        if rest.lower() in ("off", "closed"):
            for d in days:
                schedule[d] = []
            continue
        intervals = []
        for part in (p.strip() for p in rest.split(",")):
            m = _TIME_RANGE.match(part)
            if not m:
                intervals = None
                break
            h1, m1, h2, m2 = map(int, m.groups())
            if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
                intervals = None
                break
            start, end = h1 * 60 + m1, h2 * 60 + m2
            intervals.append((start, end + 24 * 60 if end <= start else end))
        if not intervals:
            understood = False
            continue
        for d in days:
            schedule[d] = intervals
    return (schedule, understood) if any_rule else None


def is_open_at(raw, weekday, minute):
    """Is a place open at `minute` (0-1439) on `weekday` (Monday = 0)? True / False, or None if unknown.

    False needs fully understood hours; anything unclear is None, never a guess."""
    if not raw or not isinstance(raw, str) or len(raw) > 255:
        return None
    if raw.strip().lower() in ALWAYS_OPEN:
        return True
    parsed = _weekly_schedule(raw)
    if parsed is None:
        return None
    schedule, understood = parsed
    if any(s <= minute < e for s, e in schedule.get(weekday, [])):
        return True
    if any(e > 1440 and s <= minute + 1440 < e for s, e in schedule.get((weekday - 1) % 7, [])):
        return True                                   # an overnight opening that began yesterday
    return False if understood else None


def parse_opening_hours(raw):
    """Return (open_evening, open_late) from an OSM opening_hours string.

    True is only returned when the text proves it. False needs a fully understood string.
    Anything else (sunrise/sunset, comments, odd syntax) gives None = unknown.
    """
    if not raw or not isinstance(raw, str) or len(raw) > 255:
        return None, None
    text = raw.strip()
    if text.lower() in ALWAYS_OPEN:
        return True, True

    intervals, understood = [], True
    for rule in (r.strip() for r in text.split(";")):
        if not rule:
            continue
        rest = _DAY_SPEC.sub("", rule, count=1).strip()
        if rest.lower() in ("off", "closed"):
            continue
        parsed = []
        for part in (p.strip() for p in rest.split(",")):
            match = _TIME_RANGE.match(part)
            if not match:
                parsed = None
                break
            h1, m1, h2, m2 = map(int, match.groups())
            if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
                parsed = None
                break
            start, end = h1 * 60 + m1, h2 * 60 + m2
            if end <= start:                      # runs past midnight, e.g. 17:00-02:00
                end += 24 * 60
            parsed.append((start, end))
        if not parsed:
            understood = False
        else:
            intervals.extend(parsed)

    if not intervals:
        return None, None
    evening = True if any(s < EVENING_END and e > EVENING_START for s, e in intervals) else (False if understood else None)
    late = True if any(e > LATE_AFTER for s, e in intervals) else (False if understood else None)
    return evening, late


# ---------------------------------------------------------------- contact + misc fields
_URL = re.compile(r"https?://\S{3,290}")
_PHONE = re.compile(r"[0-9+()\-. /]{5,40}")


def clean_website(tags):
    for key in ("website", "contact:website", "url"):
        value = str(tags.get(key, "")).split(";")[0].strip()
        if value.lower().startswith("www."):
            value = "https://" + value
        if value and _URL.fullmatch(value) and len(value) <= 300:
            return value
    return None


def clean_phone(tags):
    for key in ("phone", "contact:phone"):
        for part in re.split(r"[;,]", str(tags.get(key, ""))):
            part = part.strip()
            if part and _PHONE.fullmatch(part):
                return part
    return None


def clean_min_age(tags):
    value = str(tags.get("min_age", "")).strip()
    return int(value) if value.isdigit() and 0 <= int(value) <= 99 else None


def build_address(tags):
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    place = tags.get("addr:suburb") or tags.get("addr:city") or tags.get("addr:town")
    text = ", ".join(p for p in (street, place) if p)
    return text[:200] or None


def build_tags(tags, source_tag):
    out = [f"osm:{source_tag}"]
    if tags.get("live_music") == "yes":
        out.append("live_music")
    if tags.get("outdoor_seating") == "yes":
        out.append("outdoor_seating")
    if tags.get("wheelchair") == "yes":
        out.append("wheelchair_accessible")
    return ",".join(out)[:255]
