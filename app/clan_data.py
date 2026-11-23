"""Clan data: loads the base surname list, merges the optional enrichment file, validates it.

Base data      data/surnames.json            (never modified by the app)
Enrichment     data/clans_enrichment.json    {surname: {field: value, ...}}, every field optional

Unknown or invalid enrichment never crashes the app: problems are collected in
`ClanStore.warnings` and logged at startup, and the offending value is ignored.
"""
import json
import logging
import re
import unicodedata
from difflib import get_close_matches
from urllib.parse import quote
from pathlib import Path

log = logging.getLogger("ikhaya.clans")

CONFIDENCE_LEVELS = ("verified", "oral-tradition", "unverified")
# Placeholder text used by 216 of the 224 base records; it carries no information.
GENERIC_ORIGIN = "Historical origins tied to the KwaZulu-Natal region."
MAX_QUERY_LEN = 80
FUZZY_CUTOFF = 0.78

ORIGIN_FIELDS = ("summary", "region", "lat", "lng", "migration_note")

# field name -> kind of value it must hold
FIELDS = {
    "alt_spellings": "str_list",
    "izithakazelo_notes": "notes",
    "meaning": "str",
    "ancestor": "str",
    "origin": "origin",
    "related_clans": "str_list",
    "taboos_or_totem": "str",
    "notable_people": "str_list",
    "today_found_in": "str_list",
    "sources": "str_list",
    "confidence": "confidence",
}


def normalize(text):
    """Spelling-tolerant key: lowercase, accents and punctuation removed, doubled letters collapsed.

    "Ntombela", "Ntombella" and "NTOMBÉLA" all become "ntombela".
    """
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "", text.lower())
    return re.sub(r"(.)\1+", r"\1", text)


def split_praise_names(praise_poetry):
    """'Jali, Ngcolosi, Myeni' -> ['Jali', 'Ngcolosi', 'Myeni']."""
    return [p.strip() for p in re.split(r"[,;/]", praise_poetry or "") if p.strip()]


def empty_enrichment():
    return {name: None for name in FIELDS}


def _blank(value):
    return value is None or value == "" or value == [] or value == {}


def _clean_value(kind, value, where, warn):
    """Return the validated value, or None (after warning) if it is the wrong shape."""
    if _blank(value):
        return None

    if kind == "str":
        if isinstance(value, str):
            return value.strip() or None
        warn(f"{where}: expected text")

    elif kind == "str_list":
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return [v.strip() for v in value if v.strip()] or None
        warn(f"{where}: expected a list of text values")

    elif kind == "notes":
        if isinstance(value, list) and all(isinstance(v, dict) and isinstance(v.get("name"), str) for v in value):
            cleaned = []
            for item in value:
                extra = set(item) - {"name", "note"}
                if extra:
                    warn(f"{where}: unknown keys {sorted(extra)}")
                note = item.get("note")
                cleaned.append({"name": item["name"].strip(), "note": note.strip() if isinstance(note, str) and note.strip() else None})
            return cleaned
        warn(f"{where}: expected a list of {{name, note}} objects")

    elif kind == "confidence":
        if value in CONFIDENCE_LEVELS:
            return value
        warn(f"{where}: must be one of {CONFIDENCE_LEVELS}")

    elif kind == "origin":
        if not isinstance(value, dict):
            warn(f"{where}: expected an object")
            return None
        for key in set(value) - set(ORIGIN_FIELDS):
            warn(f"{where}: unknown field '{key}'")
        origin = {k: value.get(k) for k in ORIGIN_FIELDS}
        for key in ("summary", "region", "migration_note"):
            if origin[key] is not None and not (isinstance(origin[key], str) and origin[key].strip()):
                origin[key] = None
        lat, lng = origin["lat"], origin["lng"]
        coords_ok = False
        if lat is not None or lng is not None:
            numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lng))
            if not numeric:
                warn(f"{where}: lat and lng must both be numbers")
            elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
                warn(f"{where}: coordinates out of range (lat {lat}, lng {lng})")
            else:
                coords_ok = True
        if not coords_ok:
            origin["lat"] = origin["lng"] = None
        return origin if any(v is not None for v in origin.values()) else None

    return None


class ClanStore:
    """All clans merged with their enrichment, plus lookups by spelling-tolerant key."""

    def __init__(self, base_path, enrichment_path=None):
        self.warnings = []
        self.clans = []
        self._by_key = {}

        base = json.loads(Path(base_path).read_text(encoding="utf-8")).get("clans", [])
        enrichment = self._load_enrichment(enrichment_path)
        self._merge(base, enrichment)

        for message in self.warnings:
            log.warning("clan data: %s", message)

    # ---- loading -------------------------------------------------------
    def _warn(self, message):
        self.warnings.append(message)

    def _load_enrichment(self, path):
        if not path or not Path(path).exists():
            return {}
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._warn(f"could not read {Path(path).name}: {exc}")
            return {}
        if not isinstance(raw, dict):
            self._warn(f"{Path(path).name}: top level must be an object keyed by surname")
            return {}
        return {k: v for k, v in raw.items() if not str(k).startswith("_")}   # "_format" etc. are notes

    def _merge(self, base, enrichment):
        base_keys = {normalize(c["surname"]): c["surname"] for c in base}
        validated = {}
        for surname, entry in enrichment.items():
            key = normalize(surname)
            if key not in base_keys:
                self._warn(f"enrichment for '{surname}' has no matching clan in surnames.json")
                continue
            if key in validated:
                self._warn(f"enrichment for '{surname}' duplicates another entry; ignored")
                continue
            validated[key] = self.validate_entry(base_keys[key], entry, base_keys)

        for clan in base:
            key = normalize(clan["surname"])
            data = validated.get(key) or empty_enrichment()
            record = dict(clan)                         # base fields untouched
            record["enrichment"] = data
            record["has_enrichment"] = any(not _blank(v) for v in data.values())
            record["praise_names"] = split_praise_names(clan.get("praise_poetry"))
            self.clans.append(record)
            self._by_key[key] = record

        # alt spellings resolve to the same record (never override a real surname)
        self._alt = {}                      # normalized alt spelling -> (display, record)
        for record in self.clans:
            for alt in record["enrichment"]["alt_spellings"] or []:
                other = self._by_key.setdefault(normalize(alt), record)
                if other is not record:
                    self._warn(f"alt spelling '{alt}' of {record['surname']} clashes with {other['surname']}")
                else:
                    self._alt[normalize(alt)] = (alt, record)

        # praise name index for reverse lookup: normalized -> {"name", "clans"}
        self._praise = {}
        for record in self.clans:
            for name in record["praise_names"]:
                entry = self._praise.setdefault(normalize(name), {"name": name, "clans": []})
                if record not in entry["clans"]:
                    entry["clans"].append(record)

    def validate_entry(self, surname, entry, base_keys):
        """Validate one enrichment entry. Returns a full dict with bad values set to None."""
        result = empty_enrichment()
        if not isinstance(entry, dict):
            self._warn(f"{surname}: entry must be an object")
            return result

        for field in entry:
            if field not in FIELDS:
                self._warn(f"{surname}: unknown field '{field}' ignored")
        for field, kind in FIELDS.items():
            result[field] = _clean_value(kind, entry.get(field), f"{surname}.{field}", self._warn)

        for related in result["related_clans"] or []:
            if normalize(related) not in base_keys:
                self._warn(f"{surname}: related clan '{related}' is not in surnames.json")
        if result["confidence"] == "verified" and not result["sources"]:
            self._warn(f"{surname}: confidence 'verified' needs at least one source")
        return result

    # ---- lookups -------------------------------------------------------
    def get(self, name):
        """Record for a surname or alternative spelling (tolerant), else None."""
        return self._by_key.get(normalize(name))

    # ---- API shapes ----------------------------------------------------
    @staticmethod
    def summary(record):
        return {
            "surname": record["surname"],
            "praise_names": record["praise_names"],
            "has_enrichment": record["has_enrichment"],
            "confidence": record["enrichment"]["confidence"],
        }

    @staticmethod
    def link(surname):
        return f"#/heritage/clans?q={quote(surname)}"

    def full_record(self, record):
        """Base fields + enrichment, with related clans resolved to links."""
        data = record["enrichment"]
        related = []
        for name in data["related_clans"] or []:
            target = self.get(name)
            related.append({
                "name": target["surname"] if target else name,
                "found": target is not None,
                "api_url": f"/api/heritage/clans/{quote(target['surname'])}" if target else None,
                "link": self.link(target["surname"]) if target else None,
            })
        return {
            "surname": record["surname"],
            "praise_poetry": record["praise_poetry"],
            "praise_names": record["praise_names"],
            "base_origin": None if record.get("origins") == GENERIC_ORIGIN else record.get("origins"),
            "has_enrichment": record["has_enrichment"],
            "enrichment": {**data, "related_clans": related or None},
        }

    # ---- search --------------------------------------------------------
    @staticmethod
    def _clean_query(q):
        return " ".join(str(q or "").split())[:MAX_QUERY_LEN]

    def _candidates(self):
        """(normalized key, display text, kind, surname) for everything searchable."""
        for record in self.clans:
            yield normalize(record["surname"]), record["surname"], "surname", record["surname"]
        for key, (alt, record) in self._alt.items():
            yield key, alt, "alt_spelling", record["surname"]
        for key, entry in self._praise.items():
            yield key, entry["name"], "praise_name", None

    def suggest(self, q, limit=8):
        """Autocomplete: prefix matches first (surnames, spellings, praise names), then contains, then fuzzy."""
        key = normalize(self._clean_query(q))
        if not key:
            return []
        order = {"surname": 0, "alt_spelling": 1, "praise_name": 2}
        prefix, contains, seen, out = [], [], set(), []
        for ckey, text, kind, surname in self._candidates():
            if ckey.startswith(key):
                prefix.append((order[kind], text.lower(), text, kind, surname))
            elif len(key) >= 3 and key in ckey:
                contains.append((order[kind], text.lower(), text, kind, surname))
        ranked = sorted(prefix) + sorted(contains)
        if len(ranked) < limit and len(key) >= 3:
            pool = {ckey: (text, kind, surname) for ckey, text, kind, surname in self._candidates()}
            for ckey in get_close_matches(key, list(pool), n=limit, cutoff=FUZZY_CUTOFF):
                text, kind, surname = pool[ckey]
                ranked.append((order[kind], text.lower(), text, kind, surname))
        for _, _, text, kind, surname in ranked:
            if text.lower() in seen:            # "Mpangazitha" as surname + praise name: list once
                continue
            seen.add(text.lower())
            out.append({"text": text, "kind": kind, "surname": surname})
            if len(out) >= limit:
                break
        return out

    def search(self, q):
        """Look up a surname (or alt spelling), and/or reverse-look-up a praise name."""
        query = self._clean_query(q)
        key = normalize(query)
        result = {"query": query, "surname_match": None, "praise_match": None, "did_you_mean": []}
        if not key:
            return result

        record = self._by_key.get(key)
        if record:
            result["surname_match"] = self.summary(record)
            result["matched_via"] = "surname" if normalize(record["surname"]) == key else "alt_spelling"
        praise = self._praise.get(key)
        if praise:
            result["praise_match"] = {
                "name": praise["name"],
                "clans": [self.summary(c) for c in sorted(praise["clans"], key=lambda c: c["surname"])],
            }

        if not record and not praise:
            result["did_you_mean"] = self.suggest(query, limit=5)
        return result
