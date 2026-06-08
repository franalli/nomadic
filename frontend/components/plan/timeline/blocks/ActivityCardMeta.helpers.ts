'use client';

import { getTopicLabel } from '@/components/plan/stages/StrategyHeroUtils';
import { canonicalCategoryKey } from '@/lib/categoryNormalization';
import type { DayBlock } from '@/types/plan-envelope';

const PRICE_LEVEL_LABEL: Record<number, string> = {
  0: 'Free',
  1: '$',
  2: '$$',
  3: '$$$',
  4: '$$$$',
};

function toPriceLevelLabel(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return PRICE_LEVEL_LABEL[value];
  }
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return ['Free', '$', '$$', '$$$', '$$$$'].includes(trimmed) ? trimmed : undefined;
}

function parsePriceEstimate(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const numericMatch = trimmed.match(/(\d+(?:\.\d+)?)/);
    const numeric = numericMatch ? Number(numericMatch[1]) : Number.NaN;
    if (Number.isFinite(numeric) && numeric > 0) return numeric;
  }
  return null;
}

export function resolvePriceLevelLabel(block: DayBlock): string | undefined {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
    : null;

  return (
    toPriceLevelLabel(block.price_level)
    ?? toPriceLevelLabel(bookedTile?.price_level)
    ?? toPriceLevelLabel(meta?.price_level)
    ?? toPriceLevelLabel(block.price_estimate)
    ?? toPriceLevelLabel(bookedTile?.price_estimate)
    ?? toPriceLevelLabel(meta?.price_estimate)
  );
}

export function resolvePriceEstimate(block: DayBlock): number | null {
  const fromBlock = parsePriceEstimate(block.price_estimate);
  if (fromBlock != null) return fromBlock;

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const fromBookedTile = parsePriceEstimate(bookedTile?.price_estimate);
  if (fromBookedTile != null) return fromBookedTile;

  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
    : null;
  return parsePriceEstimate(meta?.price_estimate);
}

function formatDurationValue(hours: number): string {
  const rounded = Math.round(hours * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}h`;
}

function normalizeDurationLabel(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return formatDurationValue(value);
  }
  if (typeof value !== 'string') return undefined;

  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const lower = trimmed.toLowerCase();

  const hoursMatch = lower.match(/(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours)\b/);
  if (hoursMatch) {
    return formatDurationValue(Number(hoursMatch[1]));
  }

  const minutesMatch = lower.match(/(\d+(?:\.\d+)?)\s*(m|min|mins|minute|minutes)\b/);
  if (minutesMatch) {
    return formatDurationValue(Number(minutesMatch[1]) / 60);
  }

  return trimmed;
}

export function resolveDurationLabel(block: DayBlock): string | undefined {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
    : null;

  return (
    normalizeDurationLabel(block.duration)
    ?? normalizeDurationLabel(bookedTile?.duration)
    ?? normalizeDurationLabel(meta?.duration)
    ?? normalizeDurationLabel(meta?.duration_hours)
  );
}

export function resolveRating(block: DayBlock): number | null {
  if (typeof block.rating === 'number' && Number.isFinite(block.rating)) return block.rating;

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  if (typeof bookedTile?.rating === 'number' && Number.isFinite(bookedTile.rating)) {
    return bookedTile.rating as number;
  }

  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
    : null;
  if (typeof meta?.rating === 'number' && Number.isFinite(meta.rating)) return meta.rating as number;

  return null;
}

export function resolveReviewCount(block: DayBlock): number | null {
  if (typeof block.review_count === 'number' && Number.isFinite(block.review_count)) {
    return block.review_count;
  }

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  if (typeof bookedTile?.review_count === 'number' && Number.isFinite(bookedTile.review_count)) {
    return bookedTile.review_count as number;
  }

  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
    : null;
  if (typeof meta?.review_count === 'number' && Number.isFinite(meta.review_count)) {
    return meta.review_count as number;
  }

  return null;
}

const CATEGORY_LABEL: Record<string, string> = {
  cultural: 'Cultural',
  tours: 'Tours',
  food: 'Food',
  nature: 'Nature',
  spa: 'Spa',
  adventure: 'Adventure',
  yoga: 'Yoga',
  nightlife: 'Nightlife',
  cooking: 'Cooking',
  shopping: 'Shopping',
  temples: 'Temples',
  beach: 'Beach',
  hiking: 'Hiking',
  diving: 'Diving',
  surfing: 'Surfing',
  skiing: 'Skiing',
  cycling: 'Cycling',
  climbing: 'Climbing',
  sailing: 'Sailing',
};

// Single source of truth for "does this block render an ActivityMiniCard badge?"
// Buffer/safety/logistics blocks (arrival/departure/check-in/decompression/rest)
// route to non-badge components in RichBlockRenderer, so they must never be
// mirrored as a scheduled category. Consumed by the modal, the pill row, and the
// chip row so all category inference stays aligned with the visible badges.
const NON_ACTIVITY_TYPES = new Set([
  'arrival',
  'departure',
  'check-in',
  'check-out',
  'check_in',
  'check_out',
  'free_day',
  'rest_day',
  'buffer',
  'decompression_buffer',
]);

export function isBadgedActivityBlock(block: DayBlock): boolean {
  if (block.is_buffer) return false;
  const activityType = (block.activity_type ?? '').trim().toLowerCase();
  return !NON_ACTIVITY_TYPES.has(activityType);
}

export function resolveActivityCategory(block: DayBlock): { key: string; label: string } | null {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
    : undefined;
  const key =
    canonicalCategoryKey(block.map_type) ??
    canonicalCategoryKey(block.specialist_type) ??
    canonicalCategoryKey(bookedTile?.map_type) ??
    canonicalCategoryKey(meta?.map_type) ??
    canonicalCategoryKey((bookedTile as Record<string, unknown> | undefined)?.browse_category) ??
    canonicalCategoryKey(bookedTile?.category) ??
    canonicalCategoryKey(meta?.category);
  if (!key) return null;

  return {
    key,
    label: CATEGORY_LABEL[key] ?? getTopicLabel(key),
  };
}

export const BADGE_BG_CLASS: Record<string, string> = {
  browse: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  diving: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  hiking: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  skiing: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  cycling: 'bg-lime-100 dark:bg-lime-900/30 text-lime-700 dark:text-lime-400',
  surfing: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400',
  boating: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  sailing: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  climbing: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
  wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  yoga: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
  wellness: 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400',
  spa: 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400',
  nightlife: 'bg-fuchsia-100 dark:bg-fuchsia-900/30 text-fuchsia-700 dark:text-fuchsia-400',
  cooking: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-400',
  food: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  culture: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400',
  cultural: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400',
  temples: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400',
  sightseeing: 'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400',
  photography: 'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400',
  beach: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  shopping: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-400',
  relaxation: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
  tours: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  nature: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
  adventure: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
};

export function shouldShowIntensityBadge(block: DayBlock): boolean {
  if (!block.intensity || block.is_buffer || block.specialist_type === 'local_expert') {
    return false;
  }

  const activityLower = (block.activity_type || '').toLowerCase();
  const summaryLower = (block.summary || '').toLowerCase();
  return !['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
    (keyword) => activityLower.includes(keyword) || summaryLower.includes(keyword)
  );
}
