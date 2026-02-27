'use client';

/**
 * TimelineDayCard
 *
 * Renders a single day in the timeline: icon node, day header, and block list.
 * Extracted from TimelineThread to reduce file size.
 */

import type { LucideIcon } from 'lucide-react';
import {
  Bed,
  Camera,
  Leaf,
  MapPin,
  Mountain,
  PlaneLanding,
  PlaneTakeoff,
  ShieldAlert,
  Sparkles,
  Sun,
  Utensils,
  Waves,
  Zap,
} from 'lucide-react';
import React from 'react';

import { getDayIntensity, INTENSITY_CONFIG } from '@/lib/dayIntensity';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { TimelineBlockList, type TimelineBlockListProps } from './TimelineBlockList';

// =============================================================================
// Icon Helpers
// =============================================================================

const INTENSITY_ICON_MAP: Record<string, LucideIcon> = { Leaf, Sun, Zap };

/**
 * Get icon for a block based on its type and content.
 */
function getIconForBlock(block: DayBlock): LucideIcon {
  const type = block.activity_type?.toLowerCase() || '';
  const summary = block.summary?.toLowerCase() || '';

  if (block.buffer_type === 'arrival') return PlaneLanding;
  if (block.buffer_type === 'departure') return PlaneTakeoff;
  if (block.is_buffer || block.buffer_type) return ShieldAlert;

  if (type.includes('dive') || summary.includes('dive') || summary.includes('snorkel')) return Waves;
  if (type.includes('hike') || summary.includes('hike') || summary.includes('trek')) return Mountain;
  if (type.includes('meal') || type.includes('dining') || summary.includes('dinner') || summary.includes('lunch')) return Utensils;
  if (type.includes('hotel') || type.includes('stay') || summary.includes('check-in') || summary.includes('check in')) return Bed;
  if (type.includes('tour') || summary.includes('tour') || summary.includes('sightseeing')) return Camera;

  return Sparkles;
}

/**
 * Render the primary icon for a day based on its blocks.
 * Returns a JSX element directly to satisfy react-hooks/static-components.
 */
function renderDayIcon(card: DayCard, isFirst: boolean, isLast: boolean, className: string): React.ReactElement {
  if (isFirst || card.blocks.some((b) => b.buffer_type === 'arrival')) return <PlaneLanding className={className} />;
  if (isLast || card.blocks.some((b) => b.buffer_type === 'departure')) return <PlaneTakeoff className={className} />;
  if (card.blocks.some((b) => ['no_fly', 'acclimatization', 'rest_day'].includes(b.buffer_type || ''))) return <ShieldAlert className={className} />;
  if (card.blocks.length > 0) {
    const Icon = getIconForBlock(card.blocks[0]);
    return <Icon className={className} />;
  }
  return <MapPin className={className} />;
}

/**
 * Check if a day is a safety buffer day.
 */
function isSafetyDay(card: DayCard): boolean {
  return card.blocks.some((b) => ['no_fly', 'acclimatization', 'rest_day'].includes(b.buffer_type || ''));
}

// =============================================================================
// Props
// =============================================================================

export interface TimelineDayCardProps extends Omit<TimelineBlockListProps, 'card' | 'onBrowse'> {
  card: DayCard;
  index: number;
  totalDays: number;
  onDayClick?: (dayNumber: number) => void;
  onDayHover?: (dayNumber: number | null) => void;
  onBrowse: (dayNumber: number, date: string | null) => void;
  /** Ref callback for day header elements (map scroll sync) */
  dayHeaderRef?: (dayNumber: number, el: HTMLElement | null) => void;
}

// =============================================================================
// Component
// =============================================================================

export function TimelineDayCard({
  card,
  index,
  totalDays,
  onDayClick,
  onDayHover,
  onBrowse,
  dayHeaderRef,
  // Pass-through to TimelineBlockList
  ...blockListProps
}: TimelineDayCardProps) {
  const isFirst = index === 0;
  const isLast = index === totalDays - 1;
  const isSafety = isSafetyDay(card);

  return (
    <div className="relative z-10">
      {/* Day header with icon -- observed for scroll->map sync */}
      <button
        ref={(el) => dayHeaderRef?.(card.day_number, el)}
        data-day={card.day_number}
        type="button"
        onClick={() => onDayClick?.(card.day_number)}
        onMouseEnter={() => !document.body.hasAttribute('data-dnd-active') && onDayHover?.(card.day_number)}
        onMouseLeave={() => !document.body.hasAttribute('data-dnd-active') && onDayHover?.(null)}
        className="flex items-center gap-4 w-full text-left group mb-4"
      >
        {/* Icon node on thread */}
        <div
          className={cn(
            'timeline-node flex-shrink-0 w-9 h-9 rounded-full border flex items-center justify-center transition-colors',
            isSafety
              ? 'bg-zinc-500/10 dark:bg-zinc-500/15 border-zinc-500/50 dark:border-zinc-500/40 text-zinc-600 dark:text-zinc-400'
              : 'bg-white dark:bg-zinc-950 border-zinc-300/50 dark:border-white/20 text-zinc-500 dark:text-zinc-400 group-hover:border-emerald-500 group-hover:text-emerald-600 dark:group-hover:text-emerald-400'
          )}
        >
          {renderDayIcon(card, isFirst, isLast, 'w-4 h-4')}
        </div>

        {/* Day title */}
        <div className="flex-1 min-w-0">
          <h3
            className={cn(
              'font-semibold tracking-tight',
              'text-lg',
              isSafety ? 'text-zinc-500 dark:text-zinc-400' : 'text-zinc-900 dark:text-white'
            )}
          >
            Day {card.day_number}
            {card.date && (
              <span className="text-sm font-normal text-zinc-500 dark:text-zinc-400 ml-2">
                · {new Date(card.date + 'T00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </span>
            )}
            {(() => {
              const intensity = getDayIntensity(card.blocks);
              if (!intensity) return null;
              const cfg = INTENSITY_CONFIG[intensity];
              const Icon = INTENSITY_ICON_MAP[cfg.icon];
              return (
                <span className={cn(`ml-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${DS.textSize.mini} font-medium`, cfg.pillClass)}>
                  <Icon className="h-3 w-3" />
                  {cfg.label}
                </span>
              );
            })()}
          </h3>
          {card.label && !/^Day \d+$/i.test(card.label) && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400 truncate">{card.label}</p>
          )}
          {card.subtitle && (
            <p className="text-xs text-zinc-400 dark:text-zinc-500 truncate">{card.subtitle}</p>
          )}
        </div>
      </button>

      {/* Block list */}
      <TimelineBlockList
        card={card}
        onBrowse={onBrowse}
        {...blockListProps}
      />
    </div>
  );
}
