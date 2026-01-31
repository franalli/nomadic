/**
 * Route Utilities
 *
 * Utilities for generating GeoJSON routes and extracting map data
 * from day cards and specialist sections.
 *
 * @see docs/ux_unified_architecture.md for map-itinerary sync specification
 */

import type { DayCard, StrategySection } from '@/types/plan-envelope';

// =============================================================================
// Types
// =============================================================================

export interface MapItem {
  id: string;
  title: string;
  type: string;
  coordinates: { lat: number; lng: number };
  dayNumber?: number;
  period?: 'morning' | 'afternoon' | 'evening';
  /** Source of this map item */
  source?: 'itinerary' | 'specialist';
}

export interface RouteSegment {
  from: { lat: number; lng: number };
  to: { lat: number; lng: number };
  dayNumber: number;
  label?: string;
}

// =============================================================================
// GeoJSON Route Generation
// =============================================================================

/**
 * Generate GeoJSON LineString from day cards with coordinates.
 * Connects locations in chronological order.
 */
export function generateRouteGeoJson(
  dayCards: DayCard[]
): GeoJSON.FeatureCollection | null {
  const coordinates: [number, number][] = [];
  const dayLabels: string[] = [];

  // Extract coordinates from all blocks in order
  dayCards.forEach((card) => {
    card.blocks.forEach((block) => {
      if (block.coordinates) {
        coordinates.push([block.coordinates.lng, block.coordinates.lat]);
        dayLabels.push(`Day ${card.day_number}`);
      }
    });
  });

  // Need at least 2 points for a line
  if (coordinates.length < 2) return null;

  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: {
          type: 'LineString',
          coordinates,
        },
        properties: {
          dayLabels,
        },
      },
    ],
  };
}

/**
 * Generate route segments between consecutive days.
 * Useful for showing travel time/distance annotations.
 */
export function generateRouteSegments(dayCards: DayCard[]): RouteSegment[] {
  const segments: RouteSegment[] = [];
  let prevCoord: { lat: number; lng: number } | null = null;
  let prevDay = 0;

  dayCards.forEach((card) => {
    card.blocks.forEach((block) => {
      if (block.coordinates) {
        if (prevCoord && card.day_number !== prevDay) {
          segments.push({
            from: prevCoord,
            to: block.coordinates,
            dayNumber: card.day_number,
            label: `Day ${prevDay} → Day ${card.day_number}`,
          });
        }
        prevCoord = block.coordinates;
        prevDay = card.day_number;
      }
    });
  });

  return segments;
}

// =============================================================================
// Map Item Extraction
// =============================================================================

/**
 * Extract MapItems from day cards (itinerary blocks with coordinates).
 */
export function extractMapItemsFromDayCards(dayCards: DayCard[]): MapItem[] {
  const items: MapItem[] = [];

  dayCards.forEach((card) => {
    card.blocks.forEach((block, blockIndex) => {
      if (block.coordinates) {
        items.push({
          id: block.id || `block-${card.day_number}-${blockIndex}`,
          title: block.activity_type || block.summary || `Day ${card.day_number}`,
          type: normalizeActivityType(block.activity_type),
          coordinates: block.coordinates,
          dayNumber: card.day_number,
          period: block.period,
          source: 'itinerary',
        });
      }
    });
  });

  return items;
}

/**
 * Extract MapItems from specialist sections (POIs from recommendations).
 */
export function extractMapItemsFromSections(
  sections: StrategySection[] | undefined
): MapItem[] {
  if (!sections) return [];

  const items: MapItem[] = [];

  sections.forEach((section) => {
    section.content_added?.forEach((content, index) => {
      if (content.coordinates && content.coordinates.length === 2) {
        items.push({
          id: `poi-${section.id}-${index}`,
          title: content.title,
          type: normalizeActivityType(content.type || section.specialist_type),
          coordinates: {
            lng: content.coordinates[0],
            lat: content.coordinates[1],
          },
          source: 'specialist',
        });
      }
    });
  });

  return items;
}

/**
 * Combine map items from both itinerary and specialists.
 * Deduplicates by proximity (within 100m).
 */
export function combineMapItems(
  itineraryItems: MapItem[],
  specialistItems: MapItem[]
): MapItem[] {
  const combined = [...itineraryItems];

  // Add specialist items that aren't duplicates of itinerary items
  specialistItems.forEach((specItem) => {
    const isDuplicate = itineraryItems.some(
      (itinItem) =>
        getDistanceMeters(specItem.coordinates, itinItem.coordinates) < 100
    );

    if (!isDuplicate) {
      combined.push(specItem);
    }
  });

  return combined;
}

// =============================================================================
// Activity Type Helpers
// =============================================================================

/**
 * Normalize activity type for consistent icon/color mapping.
 */
export function normalizeActivityType(type: string | undefined): string {
  if (!type) return 'activity';

  const normalized = type.toLowerCase().trim();

  // Map variations to canonical types
  const typeMap: Record<string, string> = {
    // Diving
    diving: 'diving',
    dive: 'diving',
    scuba: 'diving',
    snorkeling: 'diving',
    snorkel: 'diving',

    // Hiking
    hiking: 'hiking',
    hike: 'hiking',
    trekking: 'hiking',
    trek: 'hiking',
    walking: 'hiking',
    'nature walk': 'hiking',

    // Hotels/Stays
    hotel: 'hotel',
    accommodation: 'hotel',
    stay: 'hotel',
    'check-in': 'hotel',
    'check-out': 'hotel',
    lodging: 'hotel',

    // Flights
    flight: 'flight',
    arrival: 'flight',
    departure: 'flight',
    airport: 'flight',

    // Temples/Culture
    temple: 'temple',
    shrine: 'temple',
    cultural: 'temple',
    heritage: 'temple',
    museum: 'temple',

    // Food
    restaurant: 'food',
    dining: 'food',
    dinner: 'food',
    lunch: 'food',
    breakfast: 'food',
    food: 'food',
    warung: 'food',

    // Tours
    tour: 'tour',
    excursion: 'tour',
    'day trip': 'tour',
    sightseeing: 'tour',

    // Beach
    beach: 'beach',
    coastal: 'beach',
    seaside: 'beach',

    // Local expert
    local_expert: 'local',
    local: 'local',
    general: 'local',
  };

  // Check for partial matches
  for (const [key, value] of Object.entries(typeMap)) {
    if (normalized.includes(key)) {
      return value;
    }
  }

  return 'activity';
}

/**
 * Extract unique activity types from map items.
 * Used for filter UI.
 */
export function extractActivityTypes(items: MapItem[]): string[] {
  const types = new Set(items.map((item) => item.type));
  return Array.from(types).sort();
}

/**
 * Get icon name for activity type (for Lucide icons).
 */
export function getActivityIcon(type: string): string {
  const iconMap: Record<string, string> = {
    diving: 'Waves',
    hiking: 'Mountain',
    hotel: 'Building2',
    flight: 'Plane',
    temple: 'Landmark',
    food: 'Utensils',
    tour: 'Compass',
    beach: 'Umbrella',
    local: 'MapPin',
    activity: 'Circle',
  };

  return iconMap[type] || 'Circle';
}

/**
 * Get color class for activity type (Tailwind).
 */
export function getActivityColor(type: string): string {
  const colorMap: Record<string, string> = {
    diving: 'text-cyan-500',
    hiking: 'text-green-500',
    hotel: 'text-purple-500',
    flight: 'text-blue-500',
    temple: 'text-amber-500',
    food: 'text-orange-500',
    tour: 'text-indigo-500',
    beach: 'text-yellow-500',
    local: 'text-emerald-500',
    activity: 'text-zinc-500',
  };

  return colorMap[type] || 'text-zinc-500';
}

// =============================================================================
// Distance Utilities
// =============================================================================

/**
 * Calculate distance between two coordinates in meters (Haversine formula).
 */
export function getDistanceMeters(
  coord1: { lat: number; lng: number },
  coord2: { lat: number; lng: number }
): number {
  const R = 6371000; // Earth's radius in meters
  const lat1 = (coord1.lat * Math.PI) / 180;
  const lat2 = (coord2.lat * Math.PI) / 180;
  const deltaLat = ((coord2.lat - coord1.lat) * Math.PI) / 180;
  const deltaLng = ((coord2.lng - coord1.lng) * Math.PI) / 180;

  const a =
    Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2) +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) * Math.sin(deltaLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

  return R * c;
}

/**
 * Calculate map bounds that fit all items with padding.
 */
export function calculateMapBounds(
  items: MapItem[]
): { sw: [number, number]; ne: [number, number] } | null {
  if (items.length === 0) return null;

  let minLng = Infinity;
  let maxLng = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;

  items.forEach((item) => {
    minLng = Math.min(minLng, item.coordinates.lng);
    maxLng = Math.max(maxLng, item.coordinates.lng);
    minLat = Math.min(minLat, item.coordinates.lat);
    maxLat = Math.max(maxLat, item.coordinates.lat);
  });

  // Add 10% padding
  const lngPadding = (maxLng - minLng) * 0.1;
  const latPadding = (maxLat - minLat) * 0.1;

  return {
    sw: [minLng - lngPadding, minLat - latPadding],
    ne: [maxLng + lngPadding, maxLat + latPadding],
  };
}

/**
 * Calculate center point from map items.
 */
export function calculateCenter(
  items: MapItem[]
): { lat: number; lng: number } | null {
  if (items.length === 0) return null;

  const sum = items.reduce(
    (acc, item) => ({
      lat: acc.lat + item.coordinates.lat,
      lng: acc.lng + item.coordinates.lng,
    }),
    { lat: 0, lng: 0 }
  );

  return {
    lat: sum.lat / items.length,
    lng: sum.lng / items.length,
  };
}
