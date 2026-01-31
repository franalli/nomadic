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
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { type DisplayTime, getTopicColor, getSpecialistBorderColor } from './types';

interface ActivityMiniCardProps {
  block: DayBlock;
  displayTime?: DisplayTime;
  onBook?: () => void;
  onUnassign?: () => void;
  isBooked?: boolean;
}

export function ActivityMiniCard({
  block,
  displayTime,
  onBook,
  onUnassign,
  isBooked,
}: ActivityMiniCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const color = getTopicColor(block.specialist_type);

  // Dynamic color classes - using template literals for Tailwind scanning
  const bgColorClass = {
    cyan: 'bg-cyan-100 dark:bg-cyan-900/30',
    emerald: 'bg-emerald-100 dark:bg-emerald-900/30',
    blue: 'bg-blue-100 dark:bg-blue-900/30',
    lime: 'bg-lime-100 dark:bg-lime-900/30',
    indigo: 'bg-indigo-100 dark:bg-indigo-900/30',
    zinc: 'bg-zinc-100 dark:bg-zinc-800/50',
  }[color] || 'bg-zinc-100 dark:bg-zinc-800/50';

  const iconColorClass = {
    cyan: 'text-cyan-500',
    emerald: 'text-emerald-500',
    blue: 'text-blue-500',
    lime: 'text-lime-500',
    indigo: 'text-indigo-500',
    zinc: 'text-zinc-500',
  }[color] || 'text-zinc-500';

  const badgeBgClass = {
    cyan: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
    emerald: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
    blue: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
    lime: 'bg-lime-100 dark:bg-lime-900/30 text-lime-700 dark:text-lime-400',
    indigo: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400',
    zinc: 'bg-zinc-100 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400',
  }[color] || 'bg-zinc-100 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400';

  // Get border color for multi-specialist visual distinction
  const borderColor = getSpecialistBorderColor(block.specialist_type);

  return (
    <div
      className="group relative flex gap-3 p-3 bg-white dark:bg-zinc-800/50 rounded-xl border hover:shadow-md transition-shadow"
      style={{ borderLeftWidth: '4px', borderLeftColor: borderColor }}
    >
      {/* Thumbnail */}
      {block.image_url ? (
        <div className="relative w-20 h-20 rounded-lg overflow-hidden shrink-0">
          <Image
            src={block.image_url}
            alt={block.summary}
            fill
            className="object-cover"
            sizes="80px"
          />
        </div>
      ) : (
        <div className={cn('w-20 h-20 rounded-lg shrink-0 flex items-center justify-center', bgColorClass)}>
          <Sparkles className={cn('w-8 h-8', iconColorClass)} />
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
            <span className={cn('text-xs px-2 py-0.5 rounded font-medium', badgeBgClass)}>
              {block.specialist_type}
            </span>
          )}

          {/* Duration */}
          {block.duration && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {block.duration}
            </span>
          )}
        </div>

        <h4 className="font-semibold text-sm mt-1.5 line-clamp-2">
          {block.activity_type || block.summary}
        </h4>

        {block.price_estimate && (
          <p className="text-xs text-muted-foreground mt-1">
            ~${block.price_estimate.toLocaleString()}
          </p>
        )}
      </div>

      {/* Action Button (Book) - only show if not booked */}
      {!isBooked && onBook && (
        <button
          onClick={onBook}
          className="self-center px-3 py-1.5 text-xs font-semibold bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-colors shrink-0"
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
