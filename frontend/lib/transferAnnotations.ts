import type { DayBlock, DayCard } from '@/types/plan-envelope';

export interface TransferAnnotation {
  fromArea: string;
  toArea: string;
  recommendedMode: string;
  estimatedDuration: string;
  tip: string;
}

interface TransportationData {
  ride_apps?: string[];
  traffic_note?: string;
}

interface NeighborhoodEntry {
  name: string;
}

interface NeighborhoodsData {
  where_to_stay?: NeighborhoodEntry[];
}

/**
 * Derive the dominant area name for a day's blocks by fuzzy-matching
 * block text against known neighborhood names.
 */
export function deriveDayArea(
  blocks: DayBlock[],
  neighborhoodNames: string[]
): string | null {
  if (!neighborhoodNames.length) return null;
  for (const name of neighborhoodNames) {
    const lower = name.toLowerCase();
    for (const b of blocks) {
      const corpus = [
        b.summary,
        b.hotel_name,
        b.booked_tile?.location_label,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      if (corpus.includes(lower)) return name;
    }
  }
  return null;
}

/**
 * Build between-day transfer annotations for consecutive days
 * whose dominant areas differ.
 */
export function buildTransferAnnotations(
  dayCards: DayCard[],
  transportation: TransportationData | null,
  neighborhoods: NeighborhoodsData | null
): Map<number, TransferAnnotation> {
  const result = new Map<number, TransferAnnotation>();
  const names = (neighborhoods?.where_to_stay ?? []).map((n) => n.name).filter(Boolean);
  if (!names.length) return result;

  for (let i = 0; i < dayCards.length - 1; i++) {
    const curr = dayCards[i];
    const next = dayCards[i + 1];
    // Skip arrival/departure-only days (single buffer block)
    const currBlocks = (curr.blocks ?? []).filter((b) => !b.buffer_type);
    const nextBlocks = (next.blocks ?? []).filter((b) => !b.buffer_type);
    if (!currBlocks.length || !nextBlocks.length) continue;

    const areaA = deriveDayArea(currBlocks, names);
    const areaB = deriveDayArea(nextBlocks, names);
    if (areaA && areaB && areaA !== areaB) {
      result.set(curr.day_number, {
        fromArea: areaA,
        toArea: areaB,
        recommendedMode: transportation?.ride_apps?.[0] ?? 'Car / taxi',
        estimatedDuration: '',
        tip: transportation?.traffic_note ?? '',
      });
    }
  }
  return result;
}
