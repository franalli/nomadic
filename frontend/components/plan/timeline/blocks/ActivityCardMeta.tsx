'use client';

import { Clock, Star } from 'lucide-react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import {
  BADGE_BG_CLASS,
  resolveDurationLabel,
  resolvePriceEstimate,
  resolvePriceLevelLabel,
  resolveRating,
  resolveReviewCount,
  shouldShowIntensityBadge,
} from './ActivityCardMeta.helpers';
import { PreferenceAttributionBadge, type PreferenceStatus } from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

export {
  BADGE_BG_CLASS,
  resolveActivityCategory,
  resolveDurationLabel,
  resolvePriceEstimate,
  resolvePriceLevelLabel,
  resolveRating,
  resolveReviewCount,
} from './ActivityCardMeta.helpers';

interface ActivityCardMetaProps {
  block: DayBlock;
  resolvedTitle: string;
  isUnschedulable: boolean;
  displayTime?: DisplayTime;
  categoryKey: string;
  categoryLabel?: string;
  preferenceStatus?: PreferenceStatus;
  alternativeTileId?: string;
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
  const resolvedRating = resolveRating(block);
  const resolvedReviewCount = resolveReviewCount(block);
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const isEstimateOnly = bookedTile?.is_estimate_only !== false;
  const showEstimatedPrice = resolvedPriceEstimate != null;
  const showPriceLevel = priceLevelLabel && !showEstimatedPrice;
  const showIntensityBadge = shouldShowIntensityBadge(block);
  const badgeBg =
    BADGE_BG_CLASS[categoryKey] || 'bg-zinc-100 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400';
  const hasContextBadges = Boolean(displayTime || categoryLabel || showIntensityBadge);

  return (
    <div className="min-w-0 flex-1">
      <h4 className="line-clamp-2 text-sm font-semibold text-zinc-900 dark:text-white">
        {resolvedTitle}
      </h4>

      {(resolvedRating != null || showPriceLevel || showEstimatedPrice || resolvedDuration) && (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {resolvedRating != null && (
            <span className="flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400">
              <Star className="h-3 w-3 fill-current text-amber-500" />
              {resolvedRating.toFixed(1)}
              {resolvedReviewCount != null && (
                <span className="ml-0.5 text-zinc-500 dark:text-zinc-400">
                  ({resolvedReviewCount >= 1000 ? `${Math.round(resolvedReviewCount / 1000)}K` : resolvedReviewCount.toLocaleString()})
                </span>
              )}
            </span>
          )}
          {showPriceLevel && <span className="text-xs text-zinc-500 dark:text-zinc-400">{priceLevelLabel}</span>}
          {showEstimatedPrice && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              {isEstimateOnly ? '~' : 'from '}${Math.round(resolvedPriceEstimate).toLocaleString()}
            </span>
          )}
          {resolvedDuration && (
            <span className="flex items-center gap-1 text-xs text-zinc-500 dark:text-zinc-400">
              <Clock className="h-3 w-3" />
              {resolvedDuration}
            </span>
          )}
        </div>
      )}

      {hasContextBadges && (
        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5">
          {categoryLabel && (
            <span className={cn('w-fit rounded px-2 py-0.5 text-xs font-medium uppercase', badgeBg)}>
              {categoryLabel.toUpperCase()}
            </span>
          )}
          {displayTime &&
            (displayTime.type === 'exact' ? (
              <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
                {displayTime.value}
              </span>
            ) : (
              <span
                className={cn(
                  DS.textSize.micro,
                  'rounded bg-zinc-100 px-1.5 py-0.5 uppercase tracking-wide text-zinc-500 dark:bg-zinc-800/50 dark:text-zinc-400'
                )}
              >
                {displayTime.value}
              </span>
            ))}
          {showIntensityBadge && (
            <span
              className={cn(
                DS.textSize.micro,
                'rounded-full border px-1.5 py-0.5 font-semibold uppercase tracking-wide',
                block.intensity === 'light' && 'border-green-500/30 bg-green-500/20 text-green-600 dark:text-green-400',
                block.intensity === 'moderate' && 'border-amber-500/30 bg-amber-500/20 text-amber-600 dark:text-amber-400',
                block.intensity === 'challenging' && 'border-red-500/30 bg-red-500/20 text-red-600 dark:text-red-400'
              )}
            >
              {block.intensity === 'light' ? 'easy' : block.intensity}
            </span>
          )}
        </div>
      )}

      {!isUnschedulable && block.summary && block.summary !== resolvedTitle && (
        <p className="mt-0.5 line-clamp-1 text-xs text-zinc-500 dark:text-zinc-400">
          {block.summary}
        </p>
      )}
      {isUnschedulable && block.unschedulable_reason && (
        <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs dark:border-amber-800/40 dark:bg-amber-900/10">
          <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-amber-700 dark:text-amber-400">
              {block.unschedulable_days_needed
                ? `Extend trip by ${block.unschedulable_days_needed} day${block.unschedulable_days_needed > 1 ? 's' : ''} to unlock`
                : 'Extend trip to unlock'}
            </div>
            <div className="mt-0.5 text-zinc-600 dark:text-zinc-400">{block.unschedulable_reason}</div>
          </div>
        </div>
      )}
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
