# Places to verify (UNVERIFIED)

**UNVERIFIED. Nothing here is in the live data.** These are well-known KwaZulu-Natal venues I can name from
general knowledge, with no address, coordinates, hours, phone numbers or ratings. Do not copy them into
`seed.py` or the database until you have checked them against an official source.

The last column only says whether a venue with a matching name appears in the OpenStreetMap download made by the
ETL (`instance/cache/`). If it does, it is already in the app through the ETL with OSM's own details. If it does not,
OpenStreetMap does not have it under that name, or the name is spelled differently.

| Venue | Area | Type | Matching name in the OSM download |
|-------|------|------|-----------------------------------|
| Suncoast Casino | Durban beachfront | casino | Suncoast Cinecentre (node/842019890); Suncoast Casino (way/43924256) |
| Sibaya Casino and Entertainment Kingdom | Umhlanga | casino | not found |
| Inkosi Albert Luthuli International Convention Centre (Durban ICC) | Durban | events venue | not found |
| The Playhouse (Playhouse Company) | Durban | theatre | Natal Playhouse (way/25841320) |
| Elizabeth Sneddon Theatre | Durban (UKZN Howard College) | theatre | not found |
| Kingsmead Stadium | Durban | stadium / events venue | not found |
| Greyville Racecourse | Durban | events venue | not found |
| uShaka Wet 'n Wild | Durban beachfront | water park | Ushaka Wet 'n Wild (way/743787951) |
| Blackrock Casino | Newcastle | casino | Blackrock Casino (way/383100770) |

Generated from the ETL cache on the day the snapshot was made. Re-check after a refresh.
