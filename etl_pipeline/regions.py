"""Which OpenStreetMap areas the ETL queries, and which of your regions each one belongs to.

EDIT THIS FILE to change how KwaZulu-Natal is grouped. Each chunk is queried on its own (one polite
request per chunk) using the OSM relation id of an administrative boundary. The relation ids were
looked up on Overpass with:

    area["ISO3166-2"="ZA-KZN"]->.kzn;
    relation(area.kzn)["boundary"="administrative"]["admin_level"="6"]; out tags;

The grouping below is a first proposal made at district level, so it is only approximate:
for example the "Drakensberg" chunks are whole districts that also contain towns such as Ladysmith
and Kokstad. Names must stay in taxonomy.REGIONS.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    name: str          # human label, also the cache file name
    relation_id: int   # OSM relation of the boundary
    region: str        # one of app.taxonomy.REGIONS
    keys: tuple = ()   # OSM keys to query (amenity / leisure / sport / tourism / shop); empty = all of them

    @property
    def area_id(self):
        return 3600000000 + self.relation_id      # Overpass area ids are relation id + 3.6 billion


# Order matters: when a feature lies in two chunks, the FIRST chunk decides its region.
# Msunduzi sits inside uMgungundlovu, so it comes first and "Midlands" means "the rest of uMgungundlovu".
CHUNKS = [
    Chunk("Msunduzi (Pietermaritzburg)", 610736, "Pietermaritzburg"),
    # The two biggest areas time out when asked for everything at once, so they are asked in smaller parts.
    Chunk("eThekwini: amenity", 610720, "Durban", ("amenity",)),
    Chunk("eThekwini: leisure + sport + shops", 610720, "Durban", ("leisure", "sport", "shop")),
    Chunk("eThekwini: tourism", 610720, "Durban", ("tourism",)),
    Chunk("iLembe", 611247, "North Coast"),
    Chunk("Ugu: venues", 610723, "South Coast", ("amenity", "leisure", "sport", "shop")),
    Chunk("Ugu: tourism", 610723, "South Coast", ("tourism",)),         # lots of guest houses: asked separately
    Chunk("uMgungundlovu", 610729, "Midlands"),
    Chunk("uThukela", 611001, "Drakensberg"),
    Chunk("Sisonke (Harry Gwala)", 611315, "Drakensberg"),
    Chunk("Zululand: amenity", 611105, "Zululand", ("amenity",)),
    Chunk("Zululand: leisure + sport + tourism + shops", 611105, "Zululand", ("leisure", "sport", "tourism", "shop")),
    Chunk("uMkhanyakude", 610712, "Zululand"),
    Chunk("King Cetshwayo", 611181, "Zululand"),
    Chunk("uMzinyathi", 611026, "Other KZN"),
    Chunk("Amajuba", 611069, "Other KZN"),
]


def chunks_for_regions(names):
    """Chunks belonging to the given region names (case-insensitive); all chunks when names is empty."""
    if not names:
        return list(CHUNKS)
    wanted = {n.strip().lower() for n in names if n.strip()}
    return [c for c in CHUNKS if c.region.lower() in wanted or c.name.lower() in wanted]
