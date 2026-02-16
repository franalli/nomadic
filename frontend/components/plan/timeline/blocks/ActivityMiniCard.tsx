/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivityMiniCard
 *
 * Rich activity card with thumbnail, duration, specialist badge,
 * and booking/context menu actions.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

'use client';

import { CheckCircle, Clock, MoreVertical, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import Image from 'next/image';
import { useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn, normalizeTitle } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { PreferenceAttributionBadge, type PreferenceStatus } from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

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
}: ActivityMiniCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const st = block.specialist_type || '';
  const isUnschedulable = block.unschedulable === true;

  // Tailwind class lookups keyed by specialist type (Tailwind JIT needs static strings)
  const bgColorClass: Record<string, string> = {
    diving: 'bg-cyan-100 dark:bg-cyan-900/30',
    hiking: 'bg-emerald-100 dark:bg-emerald-900/30',
    skiing: 'bg-blue-100 dark:bg-blue-900/30',
    cycling: 'bg-lime-100 dark:bg-lime-900/30',
    surfing: 'bg-indigo-100 dark:bg-indigo-900/30',
    boating: 'bg-indigo-100 dark:bg-indigo-900/30',
    sailing: 'bg-cyan-100 dark:bg-cyan-900/30',
    climbing: 'bg-orange-100 dark:bg-orange-900/30',
    wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30',
  };

  const iconColorClass: Record<string, string> = {
    diving: 'text-cyan-500',
    hiking: 'text-emerald-500',
    skiing: 'text-blue-500',
    cycling: 'text-lime-500',
    surfing: 'text-indigo-500',
    boating: 'text-indigo-500',
    sailing: 'text-cyan-500',
    climbing: 'text-orange-500',
    wildlife_safari: 'text-amber-500',
  };

  const badgeBgClass: Record<string, string> = {
    diving: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
    hiking: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
    skiing: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
    cycling: 'bg-lime-100 dark:bg-lime-900/30 text-lime-700 dark:text-lime-400',
    surfing: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400',
    boating: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400',
    sailing: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
    climbing: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
    wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  };

  const bg = bgColorClass[st] || 'bg-zinc-100 dark:bg-zinc-800/50';
  const iconColor = iconColorClass[st] || 'text-zinc-500';
  const badgeBg = badgeBgClass[st] || 'bg-zinc-100 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400';
  const borderAccentClass: Record<string, string> = {
    diving: 'border-l-cyan-500',
    hiking: 'border-l-emerald-500',
    skiing: 'border-l-blue-500',
    cycling: 'border-l-lime-500',
    surfing: 'border-l-indigo-500',
    boating: 'border-l-indigo-500',
    sailing: 'border-l-cyan-500',
    climbing: 'border-l-orange-500',
    wildlife_safari: 'border-l-amber-500',
  };
  const activityBorderClass = isUnschedulable
    ? 'border-l-amber-500'
    : borderAccentClass[st] || 'border-l-zinc-300 dark:border-l-zinc-600';

  return (
    <div
      className={cn(
        'group relative flex flex-col lg:flex-row gap-3 p-3 rounded-xl border border-l-4 transition-shadow',
        isUnschedulable
          ? 'bg-amber-50/50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-800/40'
          : 'bg-white dark:bg-zinc-800/50 hover:shadow-md',
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
              <span className="text-xs font-mono text-muted-foreground">
                {displayTime.value}
              </span>
            ) : (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground uppercase tracking-wide">
                {displayTime.value}
              </span>
            )
          )}

          {/* Specialist badge */}
          {block.specialist_type && (
            <span className={cn('text-xs px-2 py-0.5 rounded font-medium uppercase', badgeBg)}>
              {block.specialist_type}
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
                'text-[10px] px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wide border',
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
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {block.duration}
            </span>
          )}
        </div>

        <h4 className="font-semibold text-sm mt-1.5 line-clamp-2">
          {isUnschedulable ? block.summary : normalizeTitle(block.activity_type || block.summary)}
        </h4>

        {/* Description - show summary if different from title (skip for unschedulable, summary IS title) */}
        {!isUnschedulable && block.summary && block.summary !== normalizeTitle(block.activity_type || block.summary) && (
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
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

        {block.price_estimate && !isUnschedulable && (
          <p className="text-xs text-muted-foreground mt-1">
            ~${block.price_estimate.toLocaleString()}
          </p>
        )}

        {/* Inline Constraint Badges */}
        {block.active_constraints && block.active_constraints.length > 0 && (
          <div className="mt-4 space-y-2">
            {block.active_constraints.map((constraint: {
              id: string;
              severity: 'warning' | 'info' | 'success';
              icon: string;
              title: string;
              description: string;
            }) => (
              <div
                key={constraint.id}
                className={cn(
                  'flex items-start gap-2 p-3 rounded-lg text-xs',
                  constraint.severity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40',
                  constraint.severity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40',
                  constraint.severity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/40'
                )}
              >
                <span className="text-base flex-shrink-0">{constraint.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className={cn(
                    'font-semibold mb-0.5',
                    constraint.severity === 'warning' && 'text-amber-700 dark:text-amber-400',
                    constraint.severity === 'info' && 'text-blue-700 dark:text-blue-400',
                    constraint.severity === 'success' && 'text-emerald-700 dark:text-emerald-400'
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
          className="self-center px-3 py-1.5 text-xs font-semibold bg-zinc-900 text-white rounded-lg hover:bg-zinc-800 dark:bg-emerald-600 dark:hover:bg-emerald-500 transition-colors shrink-0"
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
            <button className="absolute top-2 right-2 p-1.5 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-muted transition-opacity">
              <MoreVertical className="w-4 h-4 text-muted-foreground" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-48 p-1">
            {onBook && (
              <button
                onClick={() => {
                  setMenuOpen(false);
                  onBook();
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted transition-colors"
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
    </div>
  );
}
