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

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { ActivityCardConstraints, ActivityCardInlineActions } from './ActivityCardActions';
import { ActivityCardMeta,resolveActivityCategory  } from './ActivityCardMeta';
import { ActivityCardPhoto } from './ActivityCardPhoto';
import { BG_COLOR_CLASS, borderAccentClass, ICON_COLOR_CLASS, resolveTitle } from './activityMiniCardParts';
import type { PreferenceStatus } from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

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
  const hasEmeraldAccent = !isUnschedulable && activityBorderClass.includes('border-l-emerald-500');
  const activityGlowClass = hasEmeraldAccent
    ? DS.shadow.emeraldInset
    : null;

  const resolvedTitle = resolveTitle(block, isUnschedulable);
  const activeConstraints = block.active_constraints ?? [];

  return (
    <div className="flex flex-col gap-1.5" data-block-id={block.id}>
      <div
        className={cn(
          'group relative flex flex-col gap-2 p-3 rounded-xl border border-l-4 transition-colors duration-150',
          isUnschedulable
            ? 'bg-amber-50/50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-800/40'
            : isHighlighted
              ? 'bg-zinc-700/70 border-emerald-500/40 shadow-soft'
              : 'bg-white dark:bg-zinc-800/50 hover:shadow-soft',
          activityBorderClass,
          activityGlowClass,
        )}
      >
        {/* Thumbnail */}
        <ActivityCardPhoto
          block={block}
          bgClass={bg}
          iconColorClass={iconColor}
          resolvedTitle={resolvedTitle}
        />

        {/* Content + Actions row */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
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
            tileId={block.booked_tile?.id}
          />
        </div>
      </div>

      {/* Constraint sub-cards -- always below the activity card */}
      <ActivityCardConstraints activeConstraints={activeConstraints} />
    </div>
  );
}
