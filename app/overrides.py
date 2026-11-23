"""Hand-maintained facts about curated places: data/place_overrides.json.

    { "Place Name": {"price_tier": "$$", "safety_score": 4.2, "region": "Durban", "website": "https://..."} }

Applied at every start (idempotent) to places matched by name. Only add values you can source;
leave a field out (or null) when unknown. Problems are logged as warnings, never fatal.
"""
import json
import logging
import re
from pathlib import Path

from app import db
from app.models import Place
from app.taxonomy import REGIONS, is_valid_subcategory

log = logging.getLogger("ikhaya.overrides")
PRICE_TIERS = ("$", "$$", "$$$")


# Each validator returns (is_valid, cleaned_value).
def _choice(options):
    return lambda v: (isinstance(v, str) and v in options, v)


def _text(max_len):
    return lambda v: (isinstance(v, str) and 0 < len(v.strip()) <= max_len, v.strip() if isinstance(v, str) else v)


def _pattern(regex):
    return lambda v: (isinstance(v, str) and re.fullmatch(regex, v.strip()) is not None, v.strip() if isinstance(v, str) else v)


def _number(low, high, integer=False):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high:
            return False, None
        if integer:
            return float(v).is_integer(), int(v)
        return True, float(v)
    return check


def _boolean(v):
    return isinstance(v, bool), v


VALIDATORS = {
    "price_tier": _choice(PRICE_TIERS),
    "safety_score": _number(0, 5),
    "opening_hours": _text(100),
    "opening_hours_raw": _text(255),
    "subcategory": lambda v: (isinstance(v, str) and is_valid_subcategory(v), v),
    "region": _choice(REGIONS),
    "website": _pattern(r"https?://\S{3,290}"),
    "phone": _pattern(r"[0-9+()\-. /]{5,40}"),
    "min_age": _number(0, 99, integer=True),
    "tags": _text(255),
    "open_evening": _boolean,
    "open_late": _boolean,
}
FIELDS = tuple(VALIDATORS)


def _validate(name, field, value):
    """Return (ok, cleaned_value). None always means "unknown" and is allowed (it clears the field)."""
    if value is None:
        return True, None
    ok, cleaned = VALIDATORS[field](value)
    if not ok:
        log.warning("place overrides: %s.%s has an invalid value %r (ignored)", name, field, value)
    return ok, cleaned


def apply_overrides(path):
    """Apply overrides; returns the list of warnings (also logged)."""
    path = Path(path)
    warnings = []
    if not path.exists():
        return warnings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object keyed by place name")
    except (OSError, ValueError) as exc:
        log.warning("place overrides: cannot read %s: %s", path.name, exc)
        return [str(exc)]

    by_name = {p.name.lower(): p for p in Place.query.all()}
    changed = False
    for name, fields in raw.items():
        if str(name).startswith("_"):
            continue
        place = by_name.get(str(name).lower())
        if place is None:
            warnings.append(f"no place named '{name}'")
            log.warning("place overrides: no place named '%s'", name)
            continue
        if not isinstance(fields, dict):
            warnings.append(f"{name}: expected an object")
            continue
        for field, value in fields.items():
            if field not in VALIDATORS:
                warnings.append(f"{name}: unknown field '{field}'")
                log.warning("place overrides: %s has unknown field '%s' (ignored)", name, field)
                continue
            ok, clean = _validate(name, field, value)
            if not ok:
                warnings.append(f"{name}.{field}: invalid value {value!r}")
            elif getattr(place, field) != clean:
                setattr(place, field, clean)
                changed = True
    if changed:
        db.session.commit()
    return warnings
