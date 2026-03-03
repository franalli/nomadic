/**
 * Ghost Timeline Adapter
 *
 * Transforms specialist content into "skeleton blocks" for the ghost timeline.
 * Used in S0_BOOTSTRAP state to show a preview of the trip before full generation.
 *
 * "Assume & Refine" philosophy: Show specialist activities immediately,
 * fill gaps with pulsing skeleton placeholders.
 */

import type { DayBlock, StrategySection } from '@/types/plan-envelope';

import { debugLog } from './debug';

const POI_MEMO_MAX_ENTRIES = 32;
const _poiMemoCache = new Map<string, MapPOI[]>();

function _trimPoiMemoCache(): void {
  if (_poiMemoCache.size <= POI_MEMO_MAX_ENTRIES) return;
  const oldest = _poiMemoCache.keys().next().value as string | undefined;
  if (oldest) {
    _poiMemoCache.delete(oldest);
  }
}

function _hashFingerprint(input: string): string {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

function _toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function _toFiniteInteger(value: unknown): number | null {
  const num = _toFiniteNumber(value);
  if (num === null) return null;
  return Math.round(num);
}

function _toIntensity(value: unknown): 'light' | 'moderate' | 'challenging' | undefined {
  const normalized = _toNormalizedKey(value);
  if (normalized === 'light' || normalized === 'moderate' || normalized === 'challenging') {
    return normalized;
  }
  return undefined;
}

function _toPriceLevel(value: unknown): number | undefined {
  const num = _toFiniteInteger(value);
  if (num === null) return undefined;
  if (num < 0 || num > 4) return undefined;
  return num;
}

function _toOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed || undefined;
}

function _normalizeMapCoordinates(
  latValue: unknown,
  lngValue: unknown
): { lat: number; lng: number } | null {
  const lat = _toFiniteNumber(latValue);
  const lng = _toFiniteNumber(lngValue);
  if (lat === null || lng === null) return null;
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat, lng };
}

/**
 * Haversine distance in km between two {lat, lng} points.
 * Used as a proximity guard against LLM-hallucinated coordinates.
 */
function _haversineKm(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number }
): number {
  const R = 6371; // Earth radius in km
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const sinLat = Math.sin(dLat / 2);
  const sinLng = Math.sin(dLng / 2);
  const h =
    sinLat * sinLat +
    Math.cos((a.lat * Math.PI) / 180) *
      Math.cos((b.lat * Math.PI) / 180) *
      sinLng * sinLng;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** Max distance (km) a POI can be from destination centroid before being filtered. */
const _MAX_POI_DISTANCE_KM = 200;

/**
 * Filter out POIs whose coordinates are likely LLM-hallucinated.
 * Computes median-based centroid of all POIs, then drops any > 200km.
 * Median is robust to majority-hallucination (mean would shift toward bad data).
 * Only applies when there are >= 3 POIs (need a meaningful cluster).
 */
function _filterProximityOutliers(pois: MapPOI[]): MapPOI[] {
  if (pois.length < 3) return pois;

  const lats = pois.map((p) => p.coordinates.lat).sort((a, b) => a - b);
  const lngs = pois.map((p) => p.coordinates.lng).sort((a, b) => a - b);
  const mid = Math.floor(lats.length / 2);
  const medianLat = lats.length % 2 ? lats[mid] : (lats[mid - 1] + lats[mid]) / 2;
  const medianLng = lngs.length % 2 ? lngs[mid] : (lngs[mid - 1] + lngs[mid]) / 2;
  const centroid = { lat: medianLat, lng: medianLng };

  const filtered = pois.filter((poi) => {
    const dist = _haversineKm(poi.coordinates, centroid);
    if (dist > _MAX_POI_DISTANCE_KM) {
      debugLog('[POI_PROXIMITY] Filtered outlier', {
        title: poi.title,
        coords: poi.coordinates,
        distKm: Math.round(dist),
        centroid,
      });
      return false;
    }
    return true;
  });

  return filtered;
}

function _toNormalizedKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

function _isBrowseBlock(block: DayBlock): boolean {
  return block.activity_provenance === 'user_browse_added';
}

const _CANONICAL_POI_TYPES = new Set<string>([
  'diving', 'hiking', 'skiing', 'cycling', 'surfing', 'sailing', 'climbing', 'wildlife_safari',
  'yoga', 'wellness', 'spa', 'nightlife', 'cooking', 'culture', 'cultural', 'temples', 'food',
  'beach', 'shopping', 'sightseeing', 'photography', 'relaxation', 'nature', 'tours',
  'adventure', 'family', 'activity',
]);

const _POI_TYPE_ALIASES: Record<string, string> = {
  cultural: 'cultural',
  food: 'food',
  nature: 'nature',
  shopping: 'shopping',
  spa: 'spa',
  tours: 'tours',
  tourist_attraction: 'tours',
  travel_agency: 'tours',
  point_of_interest: 'tours',
  museum: 'cultural',
  art_gallery: 'cultural',
  historical_landmark: 'cultural',
  cultural_landmark: 'cultural',
  monument: 'cultural',
  plaza: 'cultural',
  ruins: 'cultural',
  fountain: 'cultural',
  hindu_temple: 'temples',
  temple: 'temples',
  church: 'cultural',
  place_of_worship: 'cultural',
  synagogue: 'cultural',
  mosque: 'cultural',
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
  shopping_mall: 'shopping',
  market: 'shopping',
  store: 'shopping',
  clothing_store: 'shopping',
  department_store: 'shopping',
  beauty_salon: 'spa',
  gym: 'spa',
};

function _canonicalPoiType(value: unknown): string | null {
  const key = _toNormalizedKey(value);
  if (!key) return null;
  let mapped = _POI_TYPE_ALIASES[key] ?? key;
  if (!_CANONICAL_POI_TYPES.has(mapped)) {
    if (/(museum|landmark|historic|monument|plaza|fountain)/.test(key)) mapped = 'cultural';
    else if (/(temple|church|worship|mosque|synagogue)/.test(key)) mapped = 'temples';
    else if (/(restaurant|cafe|bar|bakery|food|meal)/.test(key)) mapped = 'food';
    else if (/(park|garden|nature|zoo|camp)/.test(key)) mapped = 'nature';
    else if (/(shop|store|market|mall)/.test(key)) mapped = 'shopping';
    else if (/(spa|wellness|gym|beauty)/.test(key)) mapped = 'spa';
    else if (/(tour|attraction|point_of_interest|visitor)/.test(key)) mapped = 'tours';
  }
  return _CANONICAL_POI_TYPES.has(mapped) ? mapped : null;
}

function _resolvePoiTypeFromBookedTile(block: DayBlock): string | null {
  const tile = block.booked_tile;
  if (!tile || typeof tile !== 'object') return null;
  const t = tile as Record<string, unknown>;
  const meta = (t.meta && typeof t.meta === 'object') ? t.meta as Record<string, unknown> : {};

  for (const candidate of [
    t.map_type,
    meta.map_type,
    t.browse_category,
    t.category,
    meta.category,
  ]) {
    const canonical = _canonicalPoiType(candidate);
    if (canonical) return canonical;
  }

  if (Array.isArray(t.tags)) {
    for (const tag of t.tags) {
      const canonical = _canonicalPoiType(tag);
      if (canonical) return canonical;
    }
  }

  return null;
}

function _resolvePoiType(block: DayBlock): string {
  const mapType = _canonicalPoiType(block.map_type);
  if (mapType) return mapType;
  const specialistType = _canonicalPoiType(block.specialist_type);
  if (specialistType) return specialistType;
  const bookedTileType = _resolvePoiTypeFromBookedTile(block);
  if (bookedTileType) return bookedTileType;
  const activityType = _canonicalPoiType(block.activity_type);
  if (activityType) return activityType;
  return 'activity';
}

function _buildPoiFingerprint(
  dayCards: import('@/types/plan-envelope').DayCard[] | undefined,
  destination: string | undefined,
  hint: string | null | undefined,
  destinationCoords?: { lat: number; lng: number } | null,
): string {
  const destinationKey = (destination ?? '').trim().toLowerCase();
  const coordsKey = destinationCoords ? `${destinationCoords.lat.toFixed(4)},${destinationCoords.lng.toFixed(4)}` : '';
  if (hint) {
    return _hashFingerprint(`hint:${hint}|dest:${destinationKey}|coords:${coordsKey}`);
  }
  if (!dayCards || dayCards.length === 0) {
    return _hashFingerprint(`empty|dest:${destinationKey}|coords:${coordsKey}`);
  }
  const tokens: string[] = [`dest:${destinationKey}`, `coords:${coordsKey}`, `days:${dayCards.length}`];
  for (const dayCard of dayCards) {
    tokens.push(`d:${dayCard.day_number}|b:${dayCard.blocks?.length ?? 0}`);
    dayCard.blocks?.forEach((block, idx) => {
      if (block.is_buffer || block.is_skeleton) return;
      const lat = block.coordinates?.lat;
      const lng = block.coordinates?.lng;
      const id = block.id ?? `${dayCard.day_number}-${idx}`;
      const bookedTile = (block.booked_tile && typeof block.booked_tile === 'object')
        ? block.booked_tile as Record<string, unknown>
        : null;
      const bookedMeta = (bookedTile?.meta && typeof bookedTile.meta === 'object')
        ? bookedTile.meta as Record<string, unknown>
        : null;
      const bookedTags = Array.isArray(bookedTile?.tags)
        ? bookedTile?.tags.map((t) => String(t)).sort().join(',')
        : '';
      const typeKey = [
        block.map_type ?? '',
        block.specialist_type ?? '',
        block.activity_type ?? '',
        block.activity_provenance ?? '',
        String(bookedTile?.map_type ?? ''),
        String(bookedMeta?.map_type ?? ''),
        String(bookedTile?.browse_category ?? ''),
        String(bookedTile?.category ?? ''),
        String(bookedMeta?.category ?? ''),
        bookedTags,
      ].join('~');
      tokens.push(`${id}:${lat ?? 'x'}:${lng ?? 'x'}:${typeKey}`);
    });
  }
  return _hashFingerprint(tokens.join('|'));
}

/**
 * Check if we have meaningful specialist content for ghost timeline.
 * Returns true if there's at least one content_added from a specialist.
 */
export function hasSpecialistContent(
  strategySections: StrategySection[] | undefined
): boolean {
  if (!strategySections) return false;

  return strategySections.some((section) => {
    if (section.specialist_type === 'local_expert') {
      return !!(
        section.destination_gallery?.length ||
        section.constraints_applied?.length ||
        section.principles?.length
      );
    }
    return (
      section.specialist_type &&
      section.specialist_type !== 'general' &&
      section.feasibility_status !== 'infeasible' &&
      section.content_added &&
      section.content_added.length > 0
    );
  });
}

/**
 * POI item for map display in Bridge Mode.
 * Matches InteractiveMap's MapItem interface.
 */
export interface MapPOI {
  id: string;
  title: string;
  type: string;
  coordinates: { lat: number; lng: number };
  dayNumber?: number;
  source?: 'itinerary' | 'specialist' | 'browse';
  intensity?: 'light' | 'moderate' | 'challenging';
  duration?: string;
  rating?: number;
  reviewCount?: number;
  priceLevel?: number;
}

/**
 * Extract POI coordinates from specialist content for map display.
 * Used in Bridge Mode to show activity locations without booking tiles.
 *
 * @param strategySections - Strategy sections from documentStore
 * @returns Array of MapPOI items for InteractiveMap
 */
export function extractPOIsFromSections(
  strategySections: StrategySection[] | undefined,
  _destination?: string
): MapPOI[] {
  if (!strategySections) return [];

  const pois: MapPOI[] = [];

  strategySections.forEach((section) => {
    // Skip general agent - no specific locations
    if (section.specialist_type === 'general') return;
    // Skip infeasible specialists
    if (section.feasibility_status === 'infeasible') return;

    section.content_added?.forEach((content, idx) => {
      // Only include if content has valid coordinates
      // Backend sends [lng, lat] format, convert to { lat, lng } for Mapbox
      if (
        content.coordinates &&
        Array.isArray(content.coordinates) &&
        content.coordinates.length === 2
      ) {
        const [lng, lat] = content.coordinates;
        const normalized = _normalizeMapCoordinates(lat, lng);
        if (!normalized) return;
        const rawContent = content as Record<string, unknown>;
        const dayNumber = _toFiniteInteger(content.day ?? rawContent.day) ?? undefined;
        const rating = _toFiniteNumber(rawContent.rating) ?? undefined;
        const reviewCount =
          _toFiniteInteger(rawContent.review_count ?? rawContent.reviewCount) ?? undefined;
        const priceLevel =
          _toPriceLevel(rawContent.price_level ?? rawContent.priceLevel) ?? undefined;
        pois.push({
          id: `poi-${section.specialist_type}-${idx}`,
          title: content.title,
          type: section.specialist_type || 'activity',
          coordinates: normalized,
          source: 'specialist',
          dayNumber,
          intensity: _toIntensity(rawContent.intensity),
          duration: _toOptionalString(rawContent.duration),
          rating,
          reviewCount,
          priceLevel,
        });
      }
    });
  });

  return _filterProximityOutliers(pois);
}

/**
 * Extract POIs from actual itinerary day_cards (source of truth after generation).
 * Use this instead of extractPOIsFromSections when itinerary exists.
 * Falls back to strategy sections if day_cards don't have coordinates.
 */
export function extractPOIsFromDayCards(
  dayCards: import('@/types/plan-envelope').DayCard[] | undefined,
  strategySections?: import('@/types/plan-envelope').StrategySection[],
  destination?: string,
  fingerprintHint?: string | null,
  destinationCoords?: { lat: number; lng: number } | null,
): MapPOI[] {
  const fingerprint = _buildPoiFingerprint(dayCards, destination, fingerprintHint, destinationCoords);
  const cached = _poiMemoCache.get(fingerprint);
  if (cached) {
    debugLog(`[VERIFY][POI_MEMO] fingerprint=${fingerprint} cache_hit=true`);
    return cached;
  }
  debugLog(`[VERIFY][POI_MEMO] fingerprint=${fingerprint} cache_hit=false`);

  if (!dayCards || dayCards.length === 0) {
    const fallback = extractPOIsFromSections(strategySections, destination);
    _poiMemoCache.set(fingerprint, fallback);
    _trimPoiMemoCache();
    debugLog('[extractPOIsFromDayCards] fallback summary', {
      reason: 'no_day_cards',
      destination,
      pois: fallback.length,
    });
    return fallback;
  }

  const pois: MapPOI[] = [];
  let totalBlocks = 0;
  let blocksWithCoords = 0;
  let skippedNoCoords = 0;
  const skippedSamples: Array<{ day: number; summary: string | null | undefined }> = [];

  dayCards.forEach((dayCard) => {
    dayCard.blocks?.forEach((block, idx) => {
      // Skip buffer/skeleton blocks
      if (block.is_buffer || block.is_skeleton) return;
      totalBlocks += 1;

      // Only include if block has coordinates
      const coords = block.coordinates;
      const normalizedCoords = _normalizeMapCoordinates(coords?.lat, coords?.lng);
      if (normalizedCoords) {
        blocksWithCoords += 1;
        // Use block.id if available, otherwise match TimelineThread's format
        const blockId = block.id || `block-${dayCard.day_number}-${idx}`;
        pois.push({
          id: blockId,
          title: block.summary || block.activity_type,
          type: _resolvePoiType(block),
          coordinates: normalizedCoords,
          dayNumber: dayCard.day_number,
          source: _isBrowseBlock(block) ? 'browse' : 'itinerary',
          intensity: block.intensity,
          duration: block.duration,
          rating: block.rating,
          reviewCount: block.review_count,
          priceLevel: block.price_level,
        });
      } else {
        skippedNoCoords += 1;
        if (skippedSamples.length < 3) {
          skippedSamples.push({
            day: dayCard.day_number,
            summary: block.summary ?? null,
          });
        }
      }
    });
  });

  debugLog('[extractPOIsFromDayCards] summary', {
    day_cards: dayCards.length,
    total_blocks: totalBlocks,
    blocks_with_coords: blocksWithCoords,
    skipped_no_coords: skippedNoCoords,
    skipped_samples: skippedSamples,
    pois: pois.length,
  });

  // If itinerary exists but no coordinates, fall back to strategy sections
  if (pois.length === 0 && strategySections) {
    const fallback = extractPOIsFromSections(strategySections, destination);
    if (fallback.length === 0 && destinationCoords) {
      const centerPoi: MapPOI = {
        id: `dest-center-${destination ?? 'unknown'}`,
        title: destination || 'Destination',
        type: 'destination-center',
        coordinates: destinationCoords,
      };
      const destFallback = [centerPoi];
      _poiMemoCache.set(fingerprint, destFallback);
      _trimPoiMemoCache();
      return destFallback;
    }
    _poiMemoCache.set(fingerprint, fallback);
    _trimPoiMemoCache();
    debugLog('[extractPOIsFromDayCards] fallback summary', {
      reason: 'no_coords_in_day_cards',
      destination,
      pois: fallback.length,
    });
    return fallback;
  }

  const filtered = _filterProximityOutliers(pois);

  // If proximity filter removed all POIs, fall back to strategy sections
  if (filtered.length === 0 && strategySections) {
    const fallback = extractPOIsFromSections(strategySections, destination);
    if (fallback.length === 0 && destinationCoords) {
      const centerPoi: MapPOI = {
        id: `dest-center-${destination ?? 'unknown'}`,
        title: destination || 'Destination',
        type: 'destination-center',
        coordinates: destinationCoords,
      };
      const destFallback = [centerPoi];
      _poiMemoCache.set(fingerprint, destFallback);
      _trimPoiMemoCache();
      return destFallback;
    }
    _poiMemoCache.set(fingerprint, fallback);
    _trimPoiMemoCache();
    return fallback;
  }

  _poiMemoCache.set(fingerprint, filtered);
  _trimPoiMemoCache();
  return filtered;
}

/**
 * Calculate center point from POIs for map initialization.
 * Returns average of all coordinates, or Dubai default if no POIs.
 */
export function calculateMapCenter(pois: MapPOI[]): { lat: number; lng: number; zoom: number } {
  const validPois = pois
    .map((poi) => _normalizeMapCoordinates(poi.coordinates?.lat, poi.coordinates?.lng))
    .filter((coords): coords is { lat: number; lng: number } => coords !== null);
  if (validPois.length === 0) {
    // Default: Dubai center
    return { lat: 25.2048, lng: 55.2708, zoom: 10 };
  }

  const avgLat = validPois.reduce((sum, p) => sum + p.lat, 0) / validPois.length;
  const avgLng = validPois.reduce((sum, p) => sum + p.lng, 0) / validPois.length;

  return { lat: avgLat, lng: avgLng, zoom: 8 };
}
