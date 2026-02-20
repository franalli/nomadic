'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivityMiniCard
 *
 * Rich activity card with thumbnail, duration, specialist badge,
 * and booking/context menu actions.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

import { CheckCircle, Clock, MoreVertical, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import Image from 'next/image';
import { useState } from 'react';

import { getTopicLabel } from '@/components/plan/stages/StrategyHeroUtils';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { DS } from '@/lib/design-system';
import { cn, normalizeTitle } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { HoldToDeleteButton } from './HoldToDeleteButton';
import { PreferenceAttributionBadge, type PreferenceStatus } from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

// Tailwind class lookups keyed by specialist type (Tailwind JIT needs static strings)
const BG_COLOR_CLASS: Record<string, string> = {
  diving: 'bg-cyan-100 dark:bg-cyan-900/30',
  hiking: 'bg-emerald-100 dark:bg-emerald-900/30',
  skiing: 'bg-blue-100 dark:bg-blue-900/30',
  cycling: 'bg-lime-100 dark:bg-lime-900/30',
  surfing: 'bg-indigo-100 dark:bg-indigo-900/30',
  boating: 'bg-cyan-100 dark:bg-cyan-900/30',
  sailing: 'bg-cyan-100 dark:bg-cyan-900/30',
  climbing: 'bg-orange-100 dark:bg-orange-900/30',
  wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30',
};

const ICON_COLOR_CLASS: Record<string, string> = {
  diving: 'text-cyan-500',
  hiking: 'text-emerald-500',
  skiing: 'text-blue-500',
  cycling: 'text-lime-500',
  surfing: 'text-indigo-500',
  boating: 'text-cyan-500',
  sailing: 'text-cyan-500',
  climbing: 'text-orange-500',
  wildlife_safari: 'text-amber-500',
};

const BADGE_BG_CLASS: Record<string, string> = {
  diving: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  hiking: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  skiing: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  cycling: 'bg-lime-100 dark:bg-lime-900/30 text-lime-700 dark:text-lime-400',
  surfing: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400',
  boating: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  sailing: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  climbing: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
  wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
};

const borderAccentClass: Record<string, string> = {
  diving: 'border-l-cyan-500',
  hiking: 'border-l-emerald-500',
  skiing: 'border-l-blue-500',
  cycling: 'border-l-lime-500',
  surfing: 'border-l-indigo-500',
  boating: 'border-l-cyan-500',
  sailing: 'border-l-cyan-500',
  climbing: 'border-l-orange-500',
  wildlife_safari: 'border-l-amber-500',
};

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
  /** Stage 17A: Per-constraint display mode (full badge vs icon pill) */
  constraintDisplayModes?: Map<string, 'full' | 'icon'>;
  /** Stage 17B: Day layout variant (compact = horizontal single-activity row) */
  variant?: 'default' | 'compact';
}

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
  constraintDisplayModes,
  variant = 'default',
}: ActivityMiniCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const st = block.specialist_type || '';
  const isUnschedulable = block.unschedulable === true;

  const bg = BG_COLOR_CLASS[st] || 'bg-zinc-100 dark:bg-zinc-800/50';
  const iconColor = ICON_COLOR_CLASS[st] || 'text-zinc-500';
  const badgeBg = BADGE_BG_CLASS[st] || 'bg-zinc-100 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400';
  const activityBorderClass = isUnschedulable
    ? 'border-l-amber-500'
    : borderAccentClass[st] || 'border-l-zinc-300 dark:border-l-zinc-600';

  // Stage 17A: Constraint display mode helpers
  const iconOnlyConstraints = (block.active_constraints ?? []).filter(
    (c) => constraintDisplayModes?.get(c.id) === 'icon'
  );
  const fullConstraints = (block.active_constraints ?? []).filter(
    (c) => !constraintDisplayModes || constraintDisplayModes.get(c.id) === 'full'
  );

  // Reusable icon pill renderer for repeated constraints
  const constraintIconPills = iconOnlyConstraints.length > 0 ? (
    <TooltipProvider>
      {iconOnlyConstraints.map((c) => (
        <Tooltip key={c.id}>
          <TooltipTrigger asChild>
            <span
              className={cn(
                'inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] cursor-help',
                c.severity === 'warning' && 'bg-amber-100 dark:bg-amber-900/20',
                c.severity === 'info' && 'bg-blue-100 dark:bg-blue-900/20',
                c.severity === 'success' && 'bg-emerald-100 dark:bg-emerald-900/20',
              )}
            >
              {c.icon}
            </span>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-[240px]">
            <p className="font-semibold text-xs">{c.title}</p>
            <p className="text-xs text-zinc-500">{c.description}</p>
          </TooltipContent>
        </Tooltip>
      ))}
    </TooltipProvider>
  ) : null;

  // ── Stage 17B: Compact variant ─────────────────────────────────────────
  if (variant === 'compact') {
    return (
      <div className={cn('group relative flex flex-col gap-1.5')}>
        {/* Horizontal row */}
        <div
          className={cn(
            'group/row relative flex items-center gap-2.5 p-2.5 rounded-xl border border-l-4 transition-shadow',
            isUnschedulable
              ? 'bg-amber-50/50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-800/40 border-l-amber-500'
              : cn('bg-white dark:bg-zinc-800/50 hover:shadow-soft', activityBorderClass),
          )}
        >
          {/* Thumbnail — 40×40 */}
          {block.image_url ? (
            <div className="relative w-10 h-10 rounded-lg overflow-hidden flex-shrink-0">
              <Image
                src={block.image_url}
                alt={block.summary}
                fill
                className="object-cover"
                sizes="40px"
              />
            </div>
          ) : (
            <div className={cn('w-10 h-10 rounded-lg flex-shrink-0 flex items-center justify-center', bg)}>
              <Sparkles className={cn('w-4 h-4', iconColor)} />
            </div>
          )}

          {/* Content */}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-zinc-900 dark:text-white truncate">
              {isUnschedulable ? block.summary : normalizeTitle(block.activity_type || block.summary)}
            </p>
            <div className="flex items-center gap-1.5 mt-0.5">
              {/* Specialist badge */}
              {block.specialist_type && (
                <span className={cn('text-xs px-1.5 py-0.5 rounded font-medium uppercase', badgeBg)}>
                  {getTopicLabel(block.specialist_type)}
                </span>
              )}
              {/* Duration */}
              {block.duration && (
                <span className="text-[10px] text-zinc-500 dark:text-zinc-400 flex items-center gap-0.5">
                  <Clock className="w-2.5 h-2.5" />
                  {block.duration}
                </span>
              )}
              {/* Icon-only constraint pills */}
              {constraintIconPills}
            </div>
          </div>

          {/* Hold-to-delete — same hover-reveal as default variant */}
          {isRemovable && onRemove && !(isBooked && onUnassign) && (
            <div className="absolute top-2 right-2 opacity-0 group-hover/row:opacity-100 transition-opacity">
              <HoldToDeleteButton onDelete={onRemove} />
            </div>
          )}
        </div>

        {/* Full constraint badges — first-occurrence or blocking severity */}
        {fullConstraints.length > 0 && (
          <div className="space-y-1.5 pl-1">
            {fullConstraints.map((constraint) => (
              <div
                key={constraint.id}
                className={cn(
                  'flex items-start gap-2 p-2.5 rounded-lg text-xs',
                  constraint.severity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40',
                  constraint.severity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40',
                  constraint.severity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/40',
                  constraint.severity === 'blocking' && 'bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/40'
                )}
              >
                <span className="text-base flex-shrink-0">{constraint.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className={cn(
                    'font-semibold mb-0.5',
                    constraint.severity === 'warning' && 'text-amber-700 dark:text-amber-400',
                    constraint.severity === 'info' && 'text-blue-700 dark:text-blue-400',
                    constraint.severity === 'success' && 'text-emerald-700 dark:text-emerald-400',
                    constraint.severity === 'blocking' && 'text-red-700 dark:text-red-400'
                  )}>
                    {constraint.title}
                  </div>
                  <div className="text-zinc-600 dark:text-zinc-400">
                    {constraint.description}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'group relative flex flex-col lg:flex-row gap-3 p-3 rounded-xl border border-l-4 transition-shadow',
        isUnschedulable
          ? 'bg-amber-50/50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-800/40'
          : 'bg-white dark:bg-zinc-800/50 hover:shadow-soft',
        activityBorderClass,
      )}
    >

      {/* Thumbnail — full-width banner on mobile, inline 80×80 on desktop */}
      {block.image_url ? (
        <div className="relative w-full h-32 lg:w-20 lg:h-20 rounded-lg overflow-hidden shrink-0">
          <Image
            src={block.image_url}
            alt={block.summary}
            fill
            className="object-cover"
            sizes="(min-width: 1024px) 80px, 100vw"
          />
        </div>
      ) : (
        <div className={cn('w-full h-32 lg:w-20 lg:h-20 rounded-lg shrink-0 flex items-center justify-center', bg)}>
          <Sparkles className={cn('w-8 h-8', iconColor)} />
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Time display */}
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

          {/* Specialist badge */}
          {block.specialist_type && (
            <span className={cn('text-xs px-2 py-0.5 rounded font-medium uppercase', badgeBg)}>
              {getTopicLabel(block.specialist_type)}
            </span>
          )}

          {/* Difficulty badge - color-coded independently of specialist */}
          {/* Hide for free/rest days, buffer blocks, and local_expert (non-activity) content */}
          {block.intensity && !block.is_buffer && block.specialist_type !== 'local_expert' && (() => {
            // Don't show intensity for "free day" style activities
            const activityLower = (block.activity_type || '').toLowerCase();
            const summaryLower = (block.summary || '').toLowerCase();
            const isFreeDay = ['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
              keyword => activityLower.includes(keyword) || summaryLower.includes(keyword)
            );
            if (isFreeDay) return null;
            return (
              <span className={cn(
                DS.textSize.micro, 'px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wide border',
                block.intensity === 'light' && 'bg-green-500/20 text-green-600 dark:text-green-400 border-green-500/30',
                block.intensity === 'moderate' && 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/30',
                block.intensity === 'challenging' && 'bg-red-500/20 text-red-600 dark:text-red-400 border-red-500/30'
              )}>
                {block.intensity === 'light' ? 'easy' : block.intensity}
              </span>
            );
          })()}

          {/* Duration */}
          {block.duration && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {block.duration}
            </span>
          )}
          {/* Stage 17A: Icon-only constraint pills for repeated constraints */}
          {constraintIconPills}
        </div>

        <h4 className="font-semibold text-sm mt-1.5 line-clamp-2 text-zinc-900 dark:text-white">
          {isUnschedulable ? block.summary : normalizeTitle(block.activity_type || block.summary)}
        </h4>

        {/* Description - show summary if different from title (skip for unschedulable, summary IS title) */}
        {!isUnschedulable && block.summary && block.summary !== normalizeTitle(block.activity_type || block.summary) && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-1">
            {block.summary}
          </p>
        )}

        {/* Unschedulable constraint chip — solution-first messaging */}
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

        {block.booked_tile?.price_estimate != null && block.booked_tile.price_estimate > 0 && !isUnschedulable && (
          <span className={cn('inline-flex items-center gap-0.5 mt-1.5 rounded px-1.5 py-0.5 font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400', DS.textSize.micro)}>
            ~${block.booked_tile.price_estimate.toLocaleString()}
          </span>
        )}

        {/* Inline Constraint Badges — full mode only (first occurrence or blocking severity) */}
        {fullConstraints.length > 0 && (
          <div className="mt-4 space-y-2">
            {fullConstraints.map((constraint) => (
              <div
                key={constraint.id}
                className={cn(
                  'flex items-start gap-2 p-3 rounded-lg text-xs',
                  constraint.severity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40',
                  constraint.severity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40',
                  constraint.severity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/40',
                  constraint.severity === 'blocking' && 'bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/40'
                )}
              >
                <span className="text-base flex-shrink-0">{constraint.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className={cn(
                    'font-semibold mb-0.5',
                    constraint.severity === 'warning' && 'text-amber-700 dark:text-amber-400',
                    constraint.severity === 'info' && 'text-blue-700 dark:text-blue-400',
                    constraint.severity === 'success' && 'text-emerald-700 dark:text-emerald-400',
                    constraint.severity === 'blocking' && 'text-red-700 dark:text-red-400'
                  )}>
                    {constraint.title}
                  </div>
                  <div className="text-zinc-600 dark:text-zinc-400">
                    {constraint.description}
                  </div>
                </div>
              </div>
            ))}
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

      {/* Action Button (Book) - only show in booking mode when not booked */}
      {mode === 'booking' && !isBooked && onBook && (
        <button
          onClick={onBook}
          className={cn(DS.actions.primary, 'self-center px-3 py-1.5 text-xs font-semibold rounded-lg shrink-0')}
        >
          Book
        </button>
      )}

      {/* Booked indicator */}
      {isBooked && !onUnassign && (
        <div className="self-center">
          <CheckCircle className="w-5 h-5 text-emerald-500" />
        </div>
      )}

      {/* Context Menu (visible on hover when booked) */}
      {isBooked && onUnassign && (
        <Popover open={menuOpen} onOpenChange={setMenuOpen}>
          <PopoverTrigger asChild>
            <button aria-label="More options" className="absolute top-2 right-2 p-1.5 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-zinc-100 dark:hover:bg-white/10 transition-opacity">
              <MoreVertical className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-48 p-1">
            {onBook && (
              <button
                onClick={() => {
                  setMenuOpen(false);
                  onBook();
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Change Selection
              </button>
            )}
            <button
              onClick={() => {
                setMenuOpen(false);
                onUnassign();
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              Remove from Itinerary
            </button>
          </PopoverContent>
        </Popover>
      )}

      {/* Hold-to-delete — only for removable, non-booked blocks */}
      {isRemovable && onRemove && !(isBooked && onUnassign) && (
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <HoldToDeleteButton onDelete={onRemove} />
        </div>
      )}
    </div>
  );
}
