'use client';

/**
 * ActivityCardActions
 *
 * Action buttons and context menu for ActivityMiniCard:
 * Book button, booked indicator, context menu (Change/Remove),
 * hold-to-delete, and constraint sub-cards.
 */

import { CheckCircle, MapPin, MoreVertical, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { trackDeeplinkClick } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { HoldToDeleteButton } from './HoldToDeleteButton';

// ---------------------------------------------------------------------------
// Constraint severity helpers
// ---------------------------------------------------------------------------

const severityWeight: Record<string, number> = {
  blocking: 4,
  warning: 3,
  info: 2,
  success: 1,
};

function mergeConstraintSeverity(
  activeConstraints: NonNullable<DayBlock['active_constraints']>
): 'blocking' | 'warning' | 'info' | 'success' {
  return activeConstraints.reduce<'blocking' | 'warning' | 'info' | 'success'>(
    (current, next) => {
      const nextSeverity = next.severity in severityWeight ? next.severity : 'info';
      return severityWeight[nextSeverity] > severityWeight[current] ? nextSeverity : current;
    },
    'info'
  );
}

// ---------------------------------------------------------------------------
// Inline actions (Book button, booked indicator, context menu, hold-to-delete)
// ---------------------------------------------------------------------------

export interface ActivityCardInlineActionsProps {
  mode: 'planning' | 'booking';
  isBooked?: boolean;
  onBook?: () => void;
  onUnassign?: () => void;
  onRemove?: () => void;
  isRemovable?: boolean;
  deeplink?: string;
  tileId?: string;
}

export function ActivityCardInlineActions({
  mode,
  isBooked,
  onBook,
  onUnassign,
  onRemove,
  isRemovable,
  deeplink,
  tileId,
}: ActivityCardInlineActionsProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <>
      {/* External deeplink — emerald glass pill */}
      {deeplink && deeplink !== '' && (
        <a
          href={deeplink}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            e.stopPropagation();
            if (tileId) trackDeeplinkClick(tileId);
          }}
          className={cn(
            'inline-flex items-center gap-1 px-2 py-1 rounded-full self-center shrink-0',
            'text-[10px] font-bold uppercase tracking-wider',
            'transition-all duration-150 active:scale-95',
            'bg-emerald-50 border border-emerald-500/30 text-emerald-700',
            'hover:bg-emerald-100 hover:border-emerald-500/60',
            'dark:bg-emerald-950/40 dark:border-emerald-500/25 dark:text-emerald-400',
            'dark:hover:bg-emerald-900/50 dark:hover:border-emerald-400/50',
            'dark:hover:shadow-[0_0_12px_-3px_rgba(16,185,129,0.3)]',
          )}
        >
          <MapPin className="w-3 h-3" />
          View
        </a>
      )}

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

      {/* Hold-to-delete -- only for removable, non-booked blocks */}
      {isRemovable && onRemove && !(isBooked && onUnassign) && (
        <div className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <HoldToDeleteButton onDelete={onRemove} />
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Constraint sub-cards
// ---------------------------------------------------------------------------

export interface ActivityCardConstraintsProps {
  activeConstraints: NonNullable<DayBlock['active_constraints']>;
}

export function ActivityCardConstraints({ activeConstraints }: ActivityCardConstraintsProps) {
  if (activeConstraints.length === 0) return null;

  const mergedSeverity = mergeConstraintSeverity(activeConstraints);
  const mergedIcons = Array.from(
    new Set(activeConstraints.map(c => c.icon).filter(Boolean))
  ).join(' ');
  const mergedTitles = Array.from(
    new Set(activeConstraints.map(c => c.title).filter(Boolean))
  ).join(' \u00B7 ');
  const mergedDescription = Array.from(
    new Set(activeConstraints.map(c => c.description).filter(Boolean))
  ).join(' \u00B7 ');

  return (
    <div className="pl-1">
      <div
        className={cn(
          'flex items-start gap-2 p-2.5 rounded-lg text-xs',
          mergedSeverity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40',
          mergedSeverity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40',
          mergedSeverity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/40',
          mergedSeverity === 'blocking' && 'bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/40'
        )}
      >
        <span className="flex-shrink-0 leading-none">
          {mergedIcons}
        </span>
        <div className="flex-1 min-w-0">
          <div className={cn(
            'font-semibold mb-0.5',
            mergedSeverity === 'warning' && 'text-amber-700 dark:text-amber-400',
            mergedSeverity === 'info' && 'text-blue-700 dark:text-blue-400',
            mergedSeverity === 'success' && 'text-emerald-700 dark:text-emerald-400',
            mergedSeverity === 'blocking' && 'text-red-700 dark:text-red-400'
          )}>
            {mergedTitles}
          </div>
          <div className="text-zinc-600 dark:text-zinc-400">
            {mergedDescription}
          </div>
        </div>
      </div>
    </div>
  );
}
