/**
 * Ghost Timeline Adapter
 *
 * Transforms specialist content into "skeleton blocks" for the ghost timeline.
 * Used in S0_BOOTSTRAP state to show a preview of the trip before full generation.
 *
 * "Assume & Refine" philosophy: Show specialist activities immediately,
 * fill gaps with pulsing skeleton placeholders.
 */

import type { DayBlock, DayCard, StrategySection } from '@/types/plan-envelope';

import { debugLog } from './debug';

/**
 * Generate ghost day cards from specialist strategy sections.
 *
 * 1. Extract content_added from each specialist section (real blocks with coordinates)
 * 2. Map to proper DayCard/DayBlock format
 * 3. Fill empty days with skeleton blocks (is_skeleton: true)
 * 4. Return mixed list ready for TimelineThread
 *
 * @param strategySections - Strategy sections from documentStore (speculative content)
 * @param duration - Trip duration in days (defaults to 5 if not set)
 * @returns DayCard[] ready for TimelineThread
 */
export function generateGhostDayCards(
  strategySections: StrategySection[] | undefined,
  duration: number = 5
): DayCard[] {
  // Track which days have real content
  const dayContentMap = new Map<number, DayBlock[]>();

  // Extract activities from specialist sections
  if (strategySections) {
    strategySections.forEach((section) => {
      // Skip general agent - it doesn't have specific activities
      if (section.specialist_type === 'general') return;
      // Skip infeasible specialists
      if (section.feasibility_status === 'infeasible') return;

      section.content_added?.forEach((content) => {
        // Assign to specified day, or distribute across middle days
        let dayNum = content.day;
        if (!dayNum || dayNum < 1 || dayNum > duration) {
          // Default: place specialist activities on day 2 (after arrival)
          dayNum = Math.min(2, duration);
        }

        const block: DayBlock = {
          id: `ghost-${section.specialist_type}-${content.title}`,
          period: 'morning', // Default to morning for specialist activities
          activity_type: content.type || section.specialist_type || 'activity',
          summary: content.title,
          // Pass through coordinates from specialist content for map integration
          // Backend sends [lng, lat] format, convert to { lat, lng } for Mapbox
          coordinates: content.coordinates
            ? { lat: content.coordinates[1], lng: content.coordinates[0] }
            : undefined,
          is_skeleton: false,
          specialist_type: section.specialist_type,
        };

        // Add to day's blocks
        const existing = dayContentMap.get(dayNum) || [];
        existing.push(block);
        dayContentMap.set(dayNum, existing);
      });
    });
  }

  // Build day cards for all days in duration
  const dayCards: DayCard[] = [];

  for (let day = 1; day <= duration; day++) {
    const realBlocks = dayContentMap.get(day) || [];

    // Determine label based on day position and content
    let label: string;
    if (day === 1) {
      label = 'Arrival day';
    } else if (day === duration) {
      label = 'Departure day';
    } else if (realBlocks.length > 0) {
      // Use first activity type for label
      const firstActivity = realBlocks[0];
      label = firstActivity.activity_type
        ? `${capitalize(firstActivity.activity_type)} day`
        : `Day ${day}`;
    } else {
      label = `Day ${day}`;
    }

    // If day has no content, add a skeleton block
    const blocks: DayBlock[] =
      realBlocks.length > 0
        ? realBlocks
        : [
            {
              id: `skeleton-day-${day}`,
              period: 'morning',
              activity_type: '',
              summary: '',
              is_skeleton: true,
            },
          ];

    dayCards.push({
      day_number: day,
      label,
      blocks,
    });
  }

  return dayCards;
}

/**
 * Check if we have meaningful specialist content for ghost timeline.
 * Returns true if there's at least one content_added from a specialist.
 */
export function hasSpecialistContent(
  strategySections: StrategySection[] | undefined
): boolean {
  if (!strategySections) return false;

  return strategySections.some(
    (section) =>
      section.specialist_type &&
      section.specialist_type !== 'general' &&
      section.feasibility_status !== 'infeasible' &&
      section.content_added &&
      section.content_added.length > 0
  );
}

/**
 * Capitalize first letter of a string.
 */
function capitalize(str: string): string {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
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
  destination?: string  // GAP 3: Added for demo POI fallback
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
        pois.push({
          id: `poi-${section.specialist_type}-${idx}`,
          title: content.title,
          type: section.specialist_type || 'activity',
          coordinates: { lat, lng },
        });
      }
    });
  });

  // U5: Demo fallback - if no POIs extracted, use curated pins for known destinations
  if (pois.length === 0 && destination) {
    // Normalize: "Bali, Indonesia" -> "Bali"
    const normalizedDest = destination
      .split(',')[0]
      .trim()
      .toLowerCase()
      .replace(/^\w/, (c) => c.toUpperCase());

    // Import is at module level, lazy access here
    const { DEMO_POIS } = require('@/lib/destination-coords');
    const demoPois = DEMO_POIS[normalizedDest] || [];

    return demoPois.map((p: { lat: number; lng: number; title: string; specialist: string }, i: number) => ({
      id: `demo-poi-${i}`,
      title: p.title,
      type: p.specialist,
      coordinates: { lat: p.lat, lng: p.lng },
    }));
  }

  return pois;
}

/**
 * Extract POIs from actual itinerary day_cards (source of truth after generation).
 * Use this instead of extractPOIsFromSections when itinerary exists.
 * Falls back to strategy sections if day_cards don't have coordinates.
 */
export function extractPOIsFromDayCards(
  dayCards: import('@/types/plan-envelope').DayCard[] | undefined,
  strategySections?: import('@/types/plan-envelope').StrategySection[],
  destination?: string
): MapPOI[] {
  if (!dayCards || dayCards.length === 0) {
    debugLog('[extractPOIsFromDayCards] No day_cards, falling back to strategy sections');
    return extractPOIsFromSections(strategySections, destination);
  }

  const pois: MapPOI[] = [];

  // Debug: Log day_cards structure
  debugLog('[extractPOIsFromDayCards] Processing day_cards:', {
    count: dayCards.length,
    blocks: dayCards.map(dc => ({
      day: dc.day_number,
      blockCount: dc.blocks?.length ?? 0,
      blocksWithCoords: dc.blocks?.filter(b => b.coordinates?.lat && b.coordinates?.lng).length ?? 0,
    })),
  });

  dayCards.forEach((dayCard) => {
    dayCard.blocks?.forEach((block, idx) => {
      // Skip buffer/skeleton blocks
      if (block.is_buffer || block.is_skeleton) return;

      // Only include if block has coordinates
      if (block.coordinates?.lat && block.coordinates?.lng) {
        // Use block.id if available, otherwise match TimelineThread's format
        const blockId = block.id || `block-${dayCard.day_number}-${idx}`;
        debugLog('[extractPOIsFromDayCards] Adding POI:', { blockId, title: block.summary, hasBlockId: !!block.id });
        pois.push({
          id: blockId,
          title: block.summary || block.activity_type,
          type: block.specialist_type || 'activity',
          coordinates: block.coordinates,
        });
      } else {
        debugLog('[extractPOIsFromDayCards] Skipping block (no coords):', { day: dayCard.day_number, idx, summary: block.summary, coords: block.coordinates });
      }
    });
  });

  debugLog('[extractPOIsFromDayCards] Extracted POIs:', pois.length);

  // If itinerary exists but no coordinates, fall back to strategy sections
  if (pois.length === 0 && strategySections) {
    debugLog('[extractPOIsFromDayCards] No POIs from day_cards, falling back to strategy sections');
    return extractPOIsFromSections(strategySections, destination);
  }

  return pois;
}

/**
 * Calculate center point from POIs for map initialization.
 * Returns average of all coordinates, or Dubai default if no POIs.
 */
export function calculateMapCenter(pois: MapPOI[]): { lat: number; lng: number; zoom: number } {
  if (pois.length === 0) {
    // Default: Dubai center
    return { lat: 25.2048, lng: 55.2708, zoom: 10 };
  }

  const avgLat = pois.reduce((sum, p) => sum + p.coordinates.lat, 0) / pois.length;
  const avgLng = pois.reduce((sum, p) => sum + p.coordinates.lng, 0) / pois.length;

  return { lat: avgLat, lng: avgLng, zoom: 11 };
}
