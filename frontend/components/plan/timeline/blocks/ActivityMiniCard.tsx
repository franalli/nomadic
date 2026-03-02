'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivityMiniCard
 *
 * Rich activity card with thumbnail, duration, specialist badge,
 * and booking/context menu actions.
 *
 * Orchestrator that delegates to:
 * - ActivityCardPhoto  (thumbnail / image section)
 * - ActivityCardMeta   (rating, price, duration, badges, description)
 * - ActivityCardActions (book, context menu, hold-to-delete, constraints)
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

import { cn, normalizeTitle } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { ActivityCardConstraints, ActivityCardInlineActions } from './ActivityCardActions';
import { ActivityCardMeta,resolveActivityCategory  } from './ActivityCardMeta';
import { ActivityCardPhoto } from './ActivityCardPhoto';
import type { PreferenceStatus } from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

// Tailwind class lookups keyed by specialist type (Tailwind JIT needs static strings)
const BG_COLOR_CLASS: Record<string, string> = {
  browse: 'bg-amber-100 dark:bg-amber-900/30',
  diving: 'bg-cyan-100 dark:bg-cyan-900/30',
  hiking: 'bg-emerald-100 dark:bg-emerald-900/30',
  skiing: 'bg-blue-100 dark:bg-blue-900/30',
  cycling: 'bg-lime-100 dark:bg-lime-900/30',
  surfing: 'bg-indigo-100 dark:bg-indigo-900/30',
  boating: 'bg-cyan-100 dark:bg-cyan-900/30',
  sailing: 'bg-cyan-100 dark:bg-cyan-900/30',
  climbing: 'bg-orange-100 dark:bg-orange-900/30',
  wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30',
  yoga: 'bg-purple-100 dark:bg-purple-900/30',
  wellness: 'bg-violet-100 dark:bg-violet-900/30',
  spa: 'bg-violet-100 dark:bg-violet-900/30',
  nightlife: 'bg-fuchsia-100 dark:bg-fuchsia-900/30',
  cooking: 'bg-pink-100 dark:bg-pink-900/30',
  food: 'bg-red-100 dark:bg-red-900/30',
  culture: 'bg-rose-100 dark:bg-rose-900/30',
  cultural: 'bg-rose-100 dark:bg-rose-900/30',
  temples: 'bg-rose-100 dark:bg-rose-900/30',
  sightseeing: 'bg-sky-100 dark:bg-sky-900/30',
  photography: 'bg-sky-100 dark:bg-sky-900/30',
  beach: 'bg-emerald-100 dark:bg-emerald-900/30',
  shopping: 'bg-pink-100 dark:bg-pink-900/30',
  relaxation: 'bg-yellow-100 dark:bg-yellow-900/30',
  tours: 'bg-blue-100 dark:bg-blue-900/30',
  nature: 'bg-green-100 dark:bg-green-900/30',
  adventure: 'bg-orange-100 dark:bg-orange-900/30',
};

const ICON_COLOR_CLASS: Record<string, string> = {
  browse: 'text-amber-600',
  diving: 'text-cyan-500',
  hiking: 'text-emerald-500',
  skiing: 'text-blue-500',
  cycling: 'text-lime-500',
  surfing: 'text-indigo-500',
  boating: 'text-cyan-500',
  sailing: 'text-cyan-500',
  climbing: 'text-orange-500',
  wildlife_safari: 'text-amber-500',
  yoga: 'text-purple-500',
  wellness: 'text-violet-500',
  spa: 'text-violet-500',
  nightlife: 'text-fuchsia-500',
  cooking: 'text-pink-500',
  food: 'text-red-500',
  culture: 'text-rose-500',
  cultural: 'text-rose-500',
  temples: 'text-rose-500',
  sightseeing: 'text-sky-500',
  photography: 'text-sky-500',
  beach: 'text-emerald-500',
  shopping: 'text-pink-500',
  relaxation: 'text-yellow-500',
  tours: 'text-blue-500',
  nature: 'text-green-500',
  adventure: 'text-orange-500',
};

const borderAccentClass: Record<string, string> = {
  browse: 'border-l-amber-500',
  diving: 'border-l-cyan-500',
  hiking: 'border-l-emerald-500',
  skiing: 'border-l-blue-500',
  cycling: 'border-l-lime-500',
  surfing: 'border-l-indigo-500',
  boating: 'border-l-cyan-500',
  sailing: 'border-l-cyan-500',
  climbing: 'border-l-orange-500',
  wildlife_safari: 'border-l-amber-500',
  yoga: 'border-l-purple-500',
  wellness: 'border-l-violet-500',
  spa: 'border-l-violet-500',
  nightlife: 'border-l-fuchsia-500',
  cooking: 'border-l-pink-500',
  food: 'border-l-red-500',
  culture: 'border-l-rose-500',
  cultural: 'border-l-rose-500',
  temples: 'border-l-rose-500',
  sightseeing: 'border-l-sky-500',
  photography: 'border-l-sky-500',
  beach: 'border-l-emerald-500',
  shopping: 'border-l-pink-500',
  relaxation: 'border-l-yellow-500',
  tours: 'border-l-blue-500',
  nature: 'border-l-green-500',
  adventure: 'border-l-orange-500',
};

// ---------------------------------------------------------------------------
// Title resolution
// ---------------------------------------------------------------------------

function resolveTitle(block: DayBlock, isUnschedulable: boolean): string {
  const rawActivityTitle = block.activity_type || '';
  const normalizedActivityTitle = normalizeTitle(rawActivityTitle);
  const summaryTitle = (block.summary || '').trim();
  const activityTitleHasUppercase = /[A-Z]/.test(rawActivityTitle);

  if (isUnschedulable) return summaryTitle;
  if (!activityTitleHasUppercase && summaryTitle) return summaryTitle;
  return normalizedActivityTitle || summaryTitle;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ActivityMiniCardProps {
  block: DayBlock;
  displayTime?: DisplayTime;
  onBook?: () => void;
  onUnassign?: () => void;
  isBooked?: boolean;
  /** Current view mode - controls Book button visibility */
  mode?: 'planning' | 'booking';
  /** Preference status for attribution badge */
  preferenceStatus?: PreferenceStatus;
  /** Alternative tile ID when AI overrode user preference */
  alternativeTileId?: string;
  /** Callback to switch to alternative tile */
  onSwitchToAlternative?: (tileId: string) => void;
  /** Callback when user completes hold-to-delete */
  onRemove?: () => void;
  /** Whether this block can be removed (not locked/buffer) */
  isRemovable?: boolean;
  /** Whether this block is map-highlighted (hovered on map) */
  isHighlighted?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ActivityMiniCard({
  block,
  displayTime,
  onBook,
  onUnassign,
  isBooked,
  mode = 'planning',
  preferenceStatus,
  alternativeTileId,
  onSwitchToAlternative,
  onRemove,
  isRemovable,
  isHighlighted,
}: ActivityMiniCardProps) {
  const activityCategory = resolveActivityCategory(block);
  const st = activityCategory?.key ?? '';
  const categoryLabel = activityCategory?.label;
  const isUnschedulable = block.unschedulable === true;

  const bg = BG_COLOR_CLASS[st] || 'bg-zinc-100 dark:bg-zinc-800/50';
  const iconColor = ICON_COLOR_CLASS[st] || 'text-zinc-500';
  const activityBorderClass = isUnschedulable
    ? 'border-l-amber-500'
    : borderAccentClass[st] || 'border-l-zinc-300 dark:border-l-zinc-600';

  const resolvedTitle = resolveTitle(block, isUnschedulable);
  const activeConstraints = block.active_constraints ?? [];

  return (
    <div className="flex flex-col gap-1.5" data-block-id={block.id}>
      <div
        className={cn(
          'group relative flex flex-col lg:flex-row gap-3 p-3 rounded-xl border border-l-4 transition-colors duration-150',
          isUnschedulable
            ? 'bg-amber-50/50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-800/40'
            : isHighlighted
              ? 'bg-zinc-700/70 border-emerald-500/40 shadow-lg shadow-emerald-500/10'
              : 'bg-white dark:bg-zinc-800/50 hover:shadow-soft',
          activityBorderClass,
        )}
      >
        {/* Thumbnail */}
        <ActivityCardPhoto
          block={block}
          bgClass={bg}
          iconColorClass={iconColor}
          resolvedTitle={resolvedTitle}
        />

        {/* Content: rating, price, duration, badges, description */}
        <ActivityCardMeta
          block={block}
          resolvedTitle={resolvedTitle}
          isUnschedulable={isUnschedulable}
          displayTime={displayTime}
          categoryKey={st}
          categoryLabel={categoryLabel}
          preferenceStatus={preferenceStatus}
          alternativeTileId={alternativeTileId}
          onSwitchToAlternative={onSwitchToAlternative}
        />

        {/* Actions: book, booked indicator, context menu, hold-to-delete */}
        <ActivityCardInlineActions
          mode={mode}
          isBooked={isBooked}
          onBook={onBook}
          onUnassign={onUnassign}
          onRemove={onRemove}
          isRemovable={isRemovable}
          deeplink={block.deeplink}
        />
      </div>

      {/* Constraint sub-cards -- always below the activity card */}
      <ActivityCardConstraints activeConstraints={activeConstraints} />
    </div>
  );
}
