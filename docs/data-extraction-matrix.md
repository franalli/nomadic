# Data Extraction Matrix — Viator vs GYG vs Google Places

## Per-Field Source Priority

| Field | 1st Choice | 2nd Choice | 3rd Choice (fallback) |
|---|---|---|---|
| **Price** | Viator `fromPrice` or GYG `price.values.amount` — pick lower | — | LLM estimate (`~$35`, `is_estimate_only=true`) |
| **Image** | Viator `media-cdn.tripadvisor.com` or GYG `cdn.getyourguide.com` — from winner | — | Unsplash placeholder keyed on category |
| **Rating** | Viator `combinedAverageRating` or GYG `overall_rating` — from winner | — | `null` (hide stars) |
| **Review count** | Viator `totalReviews` or GYG `number_of_ratings` — from winner | — | `null` (hide count) |
| **Deeplink** | Viator `productUrl` or GYG `url` — from winner | — | Google Maps search URL (no commission) |
| **Coordinates** | GYG `coordinates.lat/long` or Viator `itinerary.pointOfInterestLocation` | Google Places Geocoding API | Destination-level fallback coords |
| **Duration** | Viator `fixedDurationInMinutes` or GYG `durations[0]` — from winner | LLM specialist estimate | Default 3h |
| **Title** | LLM specialist or experience_generator (always canonical) | — | — |
| **Description** | LLM specialist `description` field | — | — |

## Winner Selection Logic

When both Viator and GYG match the same activity title:

```
1. Higher rating wins (4.8 beats 4.2)
2. Tie on rating → lower price wins ($35 beats $45)
3. Tie on both → Viator wins (more established, higher conversion)
```

One winner per tile. Loser is discarded entirely — no data is merged across providers.

## What Each API Provides

**Viator (affiliate enrichment — free, no per-call cost):**
- Real retail price (`recommendedRetailPrice`)
- Product images from `media-cdn.tripadvisor.com`
- Aggregate rating + review count
- Activity-level deeplink with affiliate tracking (`/tours/` URL)
- Duration in minutes
- Coordinates (inconsistent — only from itinerary items, not always present)

**GYG (affiliate enrichment — free, no per-call cost):**
- Real retail price
- Product images from `cdn.getyourguide.com` (needs `{format_id}` → `31` substitution)
- Rating + review count
- Activity-level deeplink (pre-signed affiliate URL)
- Duration with unit (day/hour/minute)
- Coordinates (reliable `lat`/`long` on every tour)

**Google Places (paid — $0.005/geocode, $0.12/text search):**
- Coordinates (lat/lng) — most reliable source
- Place ID (for exact Google Maps deeplink)
- Signed photo URL (via proxy)
- No real pricing, no affiliate revenue
- No booking deeplink (only Maps link)

## When Each API Is Called

```
Plan generation:
  LLM generates activity titles
    → Viator freetext match (parallel) ─┐
    → GYG search match (parallel)       ├→ Pick winner → enriched tile
    → Neither matches?                  │
       → GP Geocoding only ($0.005)     ─┘→ coordinates + Map button

Browse Activities sheet:
  → Viator destination search (parallel) ─┐
  → GYG destination search (parallel)     ├→ Merge + dedupe by title
  → Combined < max_results?              │
     → GP Text Search supplement ($0.12) ─┘→ fill remaining slots
```

## Fallback Chain Per Tile

```
Tile starts as: {title, description, category, time_of_day} from LLM

Step 1: Partner enrichment (parallel, free)
  Viator match? → price, image, rating, deeplink, duration
  GYG match?    → price, image, rating, deeplink, duration, coordinates
  Both match?   → pick winner by rating > price > Viator default

Step 2: Coordinate backfill (only if Step 1 didn't provide coords)
  GYG winner has coords? → done
  Viator winner has coords? → done
  Neither? → GP Geocoding ($0.005) → lat/lng for map pin

Step 3: Display floor (after itinerary placement)
  Has deeplink? → done (Viator or GYG affiliate link)
  No deeplink?  → Google Maps search URL (no commission)

  Has image? → done (Viator or GYG CDN)
  No image?  → Unsplash placeholder keyed on specialist_type + destination

  Has rating? → show stars + count
  No rating?  → hide rating row entirely

  Has real price? → "from $X" prefix
  No real price?  → "~$X" prefix (LLM estimate)
```

## Frontend Button Logic

Full-size cards (`ActivityCardActions`, `TileDetailsModal`) show the provider name:
```
deeplink contains "viator.com"        → "BOOK ON VIATOR" (emerald pill)
deeplink contains "getyourguide.com"  → "BOOK ON GYG" (emerald pill)
deeplink contains "google.com/maps"   → "MAP" (muted pill)
no deeplink                           → "MAP" with generated Google Maps URL
```

Compact cards (`MiniCardContent`, `TileCardContent`, `SuggestionCard`, `SuggestionCardContent`) use generic labels:
```
any partner deeplink                  → "BOOK" (emerald pill)
no partner deeplink                   → "MAP" (muted pill)
```

## What NOT to Extract

- **Don't rely on Viator/GYG coordinates as the only source** — Viator coords are inconsistent (only from itinerary items), GYG is better but may be absent. Partner coords are used when available; GP Geocoding ($0.005) serves as fallback when neither partner provides them
- **Don't merge data across Viator and GYG for the same tile** — one winner takes all fields; mixing creates attribution confusion (whose image? whose price?)
- **Don't use GP Text Search for enrichment when partners match** — it costs $0.12/call and provides no affiliate revenue
- **Don't extract GP ratings** — they're Enterprise-tier fields, not in your Pro field mask
- **Don't store partner net prices** — always use `recommendedRetailPrice` (Viator) or customer-facing price (GYG) for display
