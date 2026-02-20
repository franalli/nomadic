import type { DayCard } from '@/types/plan-envelope';

/**
 * Generate a GeoJSON FeatureCollection connecting day waypoints with a route line.
 * Uses straight lines between day centers (no Mapbox Directions API).
 *
 * Each segment is a separate Feature so the active day segment can be highlighted.
 */
export function generateRouteGeoJson(
  dayCards: DayCard[],
  highlightedDay: number | null,
): GeoJSON.FeatureCollection {
  // Build ordered waypoints: one per day (first block with valid coordinates)
  interface Waypoint {
    dayNumber: number;
    coords: [number, number]; // [lng, lat]
  }

  const waypoints: Waypoint[] = [];

  for (const day of dayCards) {
    const coordBlock = day.blocks.find(
      (b) =>
        b.coordinates &&
        typeof b.coordinates.lat === 'number' &&
        typeof b.coordinates.lng === 'number' &&
        Number.isFinite(b.coordinates.lat) &&
        Number.isFinite(b.coordinates.lng),
    );
    if (coordBlock?.coordinates) {
      waypoints.push({
        dayNumber: day.day_number,
        coords: [coordBlock.coordinates.lng, coordBlock.coordinates.lat],
      });
    }
  }

  if (waypoints.length < 2) {
    return { type: 'FeatureCollection', features: [] };
  }

  // Build per-segment features so we can highlight the active transition
  const features: GeoJSON.Feature[] = [];

  for (let i = 0; i < waypoints.length - 1; i++) {
    const fromDay = waypoints[i];
    const toDay = waypoints[i + 1];
    // Segment N connects Day N → Day N+1; it is "active" when the user is on Day N+1
    const isActive =
      highlightedDay !== null && toDay.dayNumber === highlightedDay;

    features.push({
      type: 'Feature',
      properties: {
        fromDay: fromDay.dayNumber,
        toDay: toDay.dayNumber,
        isActive,
      },
      geometry: {
        type: 'LineString',
        coordinates: [fromDay.coords, toDay.coords],
      },
    });
  }

  return { type: 'FeatureCollection', features };
}
