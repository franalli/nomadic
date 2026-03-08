'use client';

/**
 * ActivityCardMeta
 *
 * Metadata display for ActivityMiniCard: rating, price, duration,
 * category badge, time display, intensity badge, description,
 * unschedulable constraint chip, and preference attribution.
 */

import { Clock, Star } from 'lucide-react';

import { getTopicLabel } from '@/components/plan/stages/StrategyHeroUtils';
import { canonicalCategoryKey } from '@/lib/categoryNormalization';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { PreferenceAttributionBadge, type PreferenceStatus } from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

// ---------------------------------------------------------------------------
// Price helpers
// ---------------------------------------------------------------------------

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
    ? bookedTile.meta as Record<string, unknown>
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
    ? bookedTile.meta as Record<string, unknown>
    : null;
  return parsePriceEstimate(meta?.price_estimate);
}

// ---------------------------------------------------------------------------
// Duration helpers
// ---------------------------------------------------------------------------

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
    ? bookedTile.meta as Record<string, unknown>
    : null;

  return (
    normalizeDurationLabel(block.duration)
    ?? normalizeDurationLabel(bookedTile?.duration)
    ?? normalizeDurationLabel(meta?.duration)
    ?? normalizeDurationLabel(meta?.duration_hours)
  );
}

// ---------------------------------------------------------------------------
// Category resolution
// ---------------------------------------------------------------------------

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

export function resolveActivityCategory(block: DayBlock): { key: string; label: string } | null {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
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

  const baseLabel = CATEGORY_LABEL[key] ?? getTopicLabel(key);
  return {
    key,
    label: baseLabel,
  };
}

// ---------------------------------------------------------------------------
// Badge background class lookup (used by parent for border accent too)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface ActivityCardMetaProps {
  block: DayBlock;
  /** Resolved display title */
  resolvedTitle: string;
  /** Whether the block is unschedulable */
  isUnschedulable: boolean;
  /** Display time for time badge */
  displayTime?: DisplayTime;
  /** Category key (e.g., "diving") */
  categoryKey: string;
  /** Category display label */
  categoryLabel?: string;
  /** Preference status for attribution badge */
  preferenceStatus?: PreferenceStatus;
  /** Alternative tile ID when AI overrode user preference */
  alternativeTileId?: string;
  /** Callback to switch to alternative tile */
  onSwitchToAlternative?: (tileId: string) => void;
}

export function ActivityCardMeta({
  block,
  resolvedTitle,
  isUnschedulable,
  displayTime,
  categoryKey,
  categoryLabel,
  preferenceStatus,
  alternativeTileId,
  onSwitchToAlternative,
}: ActivityCardMetaProps) {
  const priceLevelLabel = resolvePriceLevelLabel(block);
  const resolvedPriceEstimate = resolvePriceEstimate(block);
  const resolvedDuration = resolveDurationLabel(block);
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const isEstimateOnly = bookedTile?.is_estimate_only !== false;
  // Prefer numeric estimate over price level ($$) when both exist
  const showEstimatedPrice = resolvedPriceEstimate != null;
  const showPriceLevel = priceLevelLabel && !showEstimatedPrice;
  const badgeBg = BADGE_BG_CLASS[categoryKey] || 'bg-zinc-100 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400';

  const showIntensityBadge = block.intensity && !block.is_buffer && block.specialist_type !== 'local_expert' && (() => {
    const activityLower = (block.activity_type || '').toLowerCase();
    const summaryLower = (block.summary || '').toLowerCase();
    return !['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
      keyword => activityLower.includes(keyword) || summaryLower.includes(keyword)
    );
  })();

  const hasContextBadges = Boolean(
    displayTime
    || categoryLabel
    || showIntensityBadge
  );

  return (
    <div className="flex-1 min-w-0">
      <h4 className="font-semibold text-sm line-clamp-2 text-zinc-900 dark:text-white">
        {resolvedTitle}
      </h4>

      {(block.rating != null || showPriceLevel || showEstimatedPrice || resolvedDuration) && (
        <div className="mt-1 flex items-center gap-2 flex-wrap">
          {block.rating != null && (
            <span className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-0.5">
              <Star className="w-3 h-3 fill-current text-amber-500" />
              {block.rating.toFixed(1)}
              {block.review_count != null && (
                <span className="text-zinc-500 dark:text-zinc-400 ml-0.5">
                  ({block.review_count >= 1000
                    ? `${Math.round(block.review_count / 1000)}K`
                    : block.review_count.toLocaleString()})
                </span>
              )}
            </span>
          )}

          {showPriceLevel && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              {priceLevelLabel}
            </span>
          )}

          {showEstimatedPrice && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              {isEstimateOnly ? '~' : 'from '}${Math.round(resolvedPriceEstimate).toLocaleString()}
            </span>
          )}

          {resolvedDuration && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {resolvedDuration}
            </span>
          )}
        </div>
      )}

      {hasContextBadges && (
        <div className="mt-1 flex items-center gap-1.5 flex-wrap min-w-0">
          {categoryLabel && (
            <span className={cn('w-fit text-xs px-2 py-0.5 rounded font-medium uppercase', badgeBg)}>
              {categoryLabel.toUpperCase()}
            </span>
          )}

          {displayTime && (
            displayTime.type === 'exact' ? (
              <span className="text-xs font-mono text-zinc-500 dark:text-zinc-400">
                {displayTime.value}
              </span>
            ) : (
              <span className={cn(DS.textSize.micro, 'px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 uppercase tracking-wide')}>
                {displayTime.value}
              </span>
            )
          )}

          {showIntensityBadge && (
            <span className={cn(
              DS.textSize.micro, 'px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wide border',
              block.intensity === 'light' && 'bg-green-500/20 text-green-600 dark:text-green-400 border-green-500/30',
              block.intensity === 'moderate' && 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/30',
              block.intensity === 'challenging' && 'bg-red-500/20 text-red-600 dark:text-red-400 border-red-500/30'
            )}>
              {block.intensity === 'light' ? 'easy' : block.intensity}
            </span>
          )}
        </div>
      )}

      {/* Description - show summary if different from title (skip for unschedulable, summary IS title) */}
      {!isUnschedulable && block.summary && block.summary !== resolvedTitle && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-1">
          {block.summary}
        </p>
      )}

      {/* Unschedulable constraint chip -- solution-first messaging */}
      {isUnschedulable && block.unschedulable_reason && (
        <div className="flex items-start gap-2 mt-2 p-2.5 rounded-lg text-xs bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40">
          <Clock className="w-3.5 h-3.5 text-amber-500 mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-amber-700 dark:text-amber-400">
              {block.unschedulable_days_needed
                ? `Extend trip by ${block.unschedulable_days_needed} day${block.unschedulable_days_needed > 1 ? 's' : ''} to unlock`
                : 'Extend trip to unlock'}
            </div>
            <div className="text-zinc-600 dark:text-zinc-400 mt-0.5">
              {block.unschedulable_reason}
            </div>
          </div>
        </div>
      )}

      {/* Preference Attribution Badge */}
      {preferenceStatus && (
        <PreferenceAttributionBadge
          status={preferenceStatus}
          alternativeTileId={alternativeTileId}
          onSwitchToAlternative={onSwitchToAlternative}
          className="mt-2"
        />
      )}
    </div>
  );
}
