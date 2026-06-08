// SSoT: specialist_registry.py CrossDomainBlock -- update both together
//
// These maps mirror the cross-domain constraint logic in
// backend/app/planner/specialist_registry.py. When specialist_registry.py
// adds or changes CrossDomainBlock entries, these must be updated to match.

/**
 * Source specialist -> categories excluded when a buffer block from that specialist
 * is present on the same day. Must mirror specialist_registry.py CrossDomainBlock
 * target_specialists exactly (currently: diving -> skiing/hiking/climbing).
 */
export const BUFFER_EXCLUSIONS: Record<string, string[]> = {
  diving: ['hiking', 'skiing', 'climbing'],
};

// ─────────────────────────────────────────────────────────────────────────────
// Category Normalization (SSoT for CATEGORY_ALIAS, canonicalCategoryKey, etc.)
//
// Superset merge of alias maps from ActivityMiniCard, UnifiedChipRow,
// ActivitiesSheet, and TripSummaryPills. Update HERE, not in consumers.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Maps backend/Google Places category keys to canonical display categories.
 * Superset of all aliases used across the codebase.
 */
export const CATEGORY_ALIAS: Record<string, string> = {
  culture: 'cultural',
  tours: 'tours',
  attraction: 'tours',
  tourist_attraction: 'tours',
  point_of_interest: 'tours',
  travel_agency: 'tours',
  cultural_attraction: 'cultural',
  museum: 'cultural',
  art_gallery: 'cultural',
  historical_landmark: 'cultural',
  cultural_landmark: 'cultural',
  monument: 'cultural',
  plaza: 'cultural',
  ruins: 'cultural',
  fountain: 'cultural',
  performing_arts_theater: 'cultural',
  hindu_temple: 'temples',
  temple: 'temples',
  church: 'temples',
  place_of_worship: 'temples',
  synagogue: 'temples',
  mosque: 'temples',
  restaurant: 'food',
  cafe: 'food',
  bar: 'food',
  bakery: 'food',
  meal_takeaway: 'food',
  meal_delivery: 'food',
  park: 'nature',
  natural_feature: 'nature',
  national_park: 'nature',
  campground: 'nature',
  zoo: 'nature',
  botanical_garden: 'nature',
  aquarium: 'nature',
  shopping_mall: 'shopping',
  market: 'shopping',
  store: 'shopping',
  clothing_store: 'shopping',
  department_store: 'shopping',
  beauty_salon: 'spa',
  gym: 'spa',
  wellness_center: 'spa',
  // Google Places yoga/nightlife/cooking types
  yoga_studio: 'yoga',
  yoga_center: 'yoga',
  night_club: 'nightlife',
  casino: 'nightlife',
  bowling_alley: 'nightlife',
  cooking_class: 'cooking',
  cooking_school: 'cooking',
  amusement_park: 'adventure',
  water_park: 'adventure',
  hiking_area: 'hiking',
  ski_resort: 'skiing',
  beach: 'beach',
};

/**
 * Tier-1 specialist constraint pattern hints.
 * Retained as the SSoT mirror of backend specialist constraint detection.
 * Note: no current consumer — category inference now mirrors the day-card
 * badges directly (resolveActivityCategory) rather than constraint text.
 */
export const TIER1_CONSTRAINT_HINTS: Record<string, RegExp[]> = {
  diving: [/\bdiv(e|ing|er|es)\b/i, /\bscuba\b/i, /\bno[- ]fly\b/i, /\bdecompression\b/i],
  hiking: [/\bhik(e|ing)\b/i, /\btrek\b/i, /\btrail\b/i],
  skiing: [/\bski(ing)?\b/i, /\bsnowboard(ing)?\b/i, /\baltitude\b/i],
  cycling: [/\bcycl(e|ing)\b/i, /\bbik(e|ing)\b/i],
  surfing: [/\bsurf(ing)?\b/i, /\bwave\b/i],
  sailing: [/\bsail(ing)?\b/i, /\byacht(ing)?\b/i, /\bmarine\b/i],
};

/**
 * Normalize a raw string to a trimmed lowercase key, or null if empty.
 */
export function toCategoryKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

/**
 * Resolve a raw category string to a canonical category key.
 *
 * 1. Tries CATEGORY_ALIAS direct lookup
 * 2. Falls through regex patterns for fuzzy matching
 * 3. Returns the mapped key (possibly identity) as fallback
 */
export function canonicalCategoryKey(value: unknown): string | null {
  const key = toCategoryKey(value);
  if (!key) return null;
  const mapped = CATEGORY_ALIAS[key] ?? key;
  if (/(culture|cultural|heritage)/.test(key)) return 'cultural';
  if (/(temple|church|worship|mosque|synagogue)/.test(key)) return 'temples';
  if (/(museum|landmark|historic|monument|plaza|fountain)/.test(key)) return 'cultural';
  if (/(restaurant|cafe|bar|bakery|food|meal)/.test(key)) return 'food';
  if (/(park|garden|nature|zoo|camp)/.test(key)) return 'nature';
  if (/(shop|store|market|mall)/.test(key)) return 'shopping';
  if (/(spa|wellness|gym|beauty)/.test(key)) return 'spa';
  if (/(yoga)/.test(key)) return 'yoga';
  if (/(nightlife|night_club|casino|bowling)/.test(key)) return 'nightlife';
  if (/(cooking|culinary)/.test(key)) return 'cooking';
  if (/(tour|point_of_interest|visitor|travel_agency)/.test(key)) return 'tours';
  return mapped;
}
