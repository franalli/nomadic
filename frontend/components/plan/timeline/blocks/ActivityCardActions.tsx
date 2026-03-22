'use client';

/**
 * ActivityCardActions
 *
 * Action buttons and context menu for ActivityMiniCard:
 * Book button, booked indicator, context menu (Change/Remove),
 * hold-to-delete, and constraint sub-cards.
 */

import { CheckCircle, MoreVertical, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { DeeplinkPill } from './ActivityCardActionsParts';
import { HoldToDeleteButton } from './HoldToDeleteButton';

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
  const [isHoverCapable, setIsHoverCapable] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }

    const mediaQuery = window.matchMedia('(hover: hover) and (pointer: fine)');
    const updateHoverCapability = () => setIsHoverCapable(mediaQuery.matches);

    updateHoverCapability();
    mediaQuery.addEventListener?.('change', updateHoverCapability);
    return () => {
      mediaQuery.removeEventListener?.('change', updateHoverCapability);
    };
  }, []);

  return (
    <>
      {/* External deeplink — emerald glass pill */}
      {deeplink && deeplink !== '' && deeplink !== '#' && (
        <DeeplinkPill deeplink={deeplink} tileId={tileId} />
      )}

      {/* Action Button (Book) - only show in booking mode when not booked */}
      {mode === 'booking' && !isBooked && onBook && (
        <button
          onClick={onBook}
          className={cn(
            DS.actions.primary,
            'self-start sm:self-center min-h-11 px-3 py-2 text-xs font-semibold rounded-lg shrink-0'
          )}
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

      {/* Context Menu (always visible on mobile/touch layouts, hover-revealed on large screens) */}
      {isBooked && onUnassign && (
        <Popover open={menuOpen} onOpenChange={setMenuOpen}>
          <PopoverTrigger asChild>
            <button
              aria-label="More options"
              className={cn(
                'absolute top-2 right-2 z-10 flex h-11 w-11 items-center justify-center rounded-full border shadow-sm transition-opacity',
                'border-zinc-200/80 bg-white/90 hover:bg-zinc-100',
                'dark:border-white/10 dark:bg-zinc-950/80 dark:hover:bg-white/10',
                isHoverCapable
                  ? 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'
                  : 'opacity-100'
              )}
            >
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
                className="flex min-h-11 w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors"
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
              className="flex min-h-11 w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              Remove from Itinerary
            </button>
          </PopoverContent>
        </Popover>
      )}

      {/* Hold-to-delete -- always visible so touch devices never depend on hover */}
      {isRemovable && onRemove && !(isBooked && onUnassign) && (
        <div
          className={cn(
            'absolute top-2 right-2 z-10 transition-opacity',
            isHoverCapable
              ? 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'
              : 'opacity-100'
          )}
        >
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

  const parts = Array.from(
    new Set(activeConstraints.map(c => c.description || c.title).filter(Boolean))
  );
  if (parts.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-zinc-500 dark:text-zinc-400">
      <ShieldCheck className="w-3.5 h-3.5 text-emerald-500/60 shrink-0" />
      <span className="truncate">{parts.join(' · ')}</span>
    </div>
  );
}
