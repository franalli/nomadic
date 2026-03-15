import type { DayCard } from '@/types/plan-envelope';

function hasFiniteCoordinate(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function buildPoiRelevantBlockFingerprint(
  block: NonNullable<DayCard['blocks']>[number],
  blockIndex: number,
): string | null {
  if (block.is_buffer || block.is_skeleton) return null;

  const coords = block.coordinates;
  const lat = hasFiniteCoordinate(coords?.lat) ? coords.lat : null;
  const lng = hasFiniteCoordinate(coords?.lng) ? coords.lng : null;
  if (lat === null || lng === null) return null;

  const bookedTile =
    block.booked_tile && typeof block.booked_tile === 'object'
      ? block.booked_tile as Record<string, unknown>
      : null;
  const bookedMeta =
    bookedTile?.meta && typeof bookedTile.meta === 'object'
      ? bookedTile.meta as Record<string, unknown>
      : null;
  const bookedTags = Array.isArray(bookedTile?.tags)
    ? bookedTile.tags.map((tag) => String(tag)).sort().join(',')
    : '';

  return [
    block.id ?? `block-${blockIndex}`,
    lat.toFixed(4),
    lng.toFixed(4),
    block.map_type ?? '',
    block.specialist_type ?? '',
    block.activity_type ?? '',
    block.activity_provenance ?? '',
    block.summary ?? '',
    block.intensity ?? '',
    block.duration ?? '',
    String(block.rating ?? ''),
    String(block.review_count ?? ''),
    String(block.price_level ?? ''),
    String(bookedTile?.map_type ?? ''),
    String(bookedTile?.category ?? ''),
    String(bookedTile?.browse_category ?? ''),
    String(bookedMeta?.map_type ?? ''),
    String(bookedMeta?.category ?? ''),
    bookedTags,
  ].join('~');
}

export function buildDayCardsFingerprint(
  cards: DayCard[] | null | undefined,
): string | null {
  if (!cards || cards.length === 0) return null;

  const poiRelevantDayTokens = cards
    .map((card) => {
      const blockFingerprints = (card.blocks ?? [])
        .map((block, index) => buildPoiRelevantBlockFingerprint(block, index))
        .filter((value): value is string => value !== null);
      if (blockFingerprints.length === 0) return null;
      return `${card.day_number}:${blockFingerprints.join(',')}`;
    })
    .filter((value): value is string => value !== null);

  if (poiRelevantDayTokens.length > 0) {
    return `${cards.length}:${poiRelevantDayTokens.join('|')}`;
  }

  return `${cards.length}:${cards
    .map((card) => {
      const blockIds = (card.blocks ?? []).map((block) => block.id ?? '').join(',');
      return `${card.day_number}:${(card.blocks ?? []).length}:${blockIds}`;
    })
    .join('|')}`;
}

export const POI_PROMOTION_STABILIZE_MS = 50;

interface PoiPromotionDelayArgs {
  settledDayCards: DayCard[] | null | undefined;
  settledFingerprint: string | null;
  nextFingerprint: string | null;
  isStreaming: boolean;
}

export function shouldDelayPoiSnapshotPromotion({
  settledFingerprint,
  nextFingerprint,
  isStreaming,
}: PoiPromotionDelayArgs): boolean {
  if (isStreaming) return false;
  if (settledFingerprint === null) return false;
  return settledFingerprint !== nextFingerprint;
}

interface PoiDayCardSnapshotArgs {
  currentDayCards: DayCard[] | null | undefined;
  currentFingerprint: string | null;
  fallbackDayCards: DayCard[] | null | undefined;
  stableDayCards: DayCard[] | null | undefined;
  stableFingerprint: string | null;
  isStreaming: boolean;
}

interface PoiDayCardSnapshot {
  dayCards: DayCard[] | null | undefined;
  fingerprint: string | null;
  nextStableDayCards: DayCard[] | null | undefined;
  nextStableFingerprint: string | null;
}

export function selectPoiDayCardSnapshot({
  currentDayCards,
  currentFingerprint,
  fallbackDayCards,
  stableDayCards,
  stableFingerprint,
  isStreaming,
}: PoiDayCardSnapshotArgs): PoiDayCardSnapshot {
  const liveDayCards = currentDayCards ?? fallbackDayCards;
  const liveFingerprint = currentFingerprint ?? buildDayCardsFingerprint(liveDayCards);

  if (isStreaming) {
    const frozenDayCards = stableDayCards ?? liveDayCards;
    const frozenFingerprint = stableFingerprint ?? buildDayCardsFingerprint(frozenDayCards);

    return {
      dayCards: frozenDayCards,
      fingerprint: frozenFingerprint,
      nextStableDayCards: frozenDayCards,
      nextStableFingerprint: frozenFingerprint,
    };
  }

  return {
    dayCards: liveDayCards,
    fingerprint: liveFingerprint,
    nextStableDayCards: liveDayCards,
    nextStableFingerprint: liveFingerprint,
  };
}
