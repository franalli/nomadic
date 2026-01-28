/**
 * BookingAnchorCard
 *
 * Interactive card for Flights/Hotels booking anchors.
 * Uses status prop to prevent broken/loading states.
 *
 * States:
 * - pending: CTA "Find Flights/Hotels" (triggers search)
 * - loading: Shows spinner, "Searching..."
 * - complete: CTA "View Options" (link to results)
 */

'use client';

import { ArrowRight, Building2, Check,Loader2, Plane } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';

export type BookingStatus = 'pending' | 'loading' | 'complete';

interface BookingAnchorCardProps {
  type: 'flights' | 'hotels';
  tripInputs: DocumentTripInputs;
  status: BookingStatus;
  onAction?: () => void;
}

export const BookingAnchorCard = memo(function BookingAnchorCard({
  type,
  tripInputs,
  status,
  onAction,
}: BookingAnchorCardProps) {
  const isFlights = type === 'flights';
  const Icon = isFlights ? Plane : Building2;

  // Extract relevant data
  const origin = tripInputs.origin || null;
  const destination = tripInputs.destination || null;
  const startDate = tripInputs.start_date || null;
  const endDate = tripInputs.end_date || null;

  // Route summary for flights
  const routeSummary = isFlights && origin && destination
    ? `${origin} → ${destination}`
    : isFlights
    ? 'Set origin & destination'
    : destination
    ? destination
    : 'Set destination';

  // Date summary
  const dateSummary = startDate && endDate
    ? `${startDate} - ${endDate}`
    : 'Dates not set';

  // CTA text based on status
  const ctaText = {
    pending: isFlights ? 'Find Flights' : 'Find Hotels',
    loading: 'Searching...',
    complete: 'View Options',
  }[status];

  // Status badge
  const statusBadge = {
    pending: { text: 'PENDING', color: 'bg-amber-500/10 text-amber-500 border-amber-500/20' },
    loading: { text: 'SEARCHING', color: 'bg-blue-500/10 text-blue-500 border-blue-500/20' },
    complete: { text: 'FOUND', color: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' },
  }[status];

  // Disable CTA if missing required data
  const canSearch = isFlights
    ? !!(origin && destination && startDate && endDate)
    : !!(destination && startDate && endDate);

  const isDisabled = status === 'loading' || (status === 'pending' && !canSearch);

  return (
    <div
      className={cn(
        'relative rounded-xl border p-4',
        'bg-white dark:bg-zinc-900',
        'border-zinc-200 dark:border-zinc-800',
        'transition-all duration-200',
        'hover:border-zinc-300 dark:hover:border-zinc-700',
        'hover:shadow-sm'
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'flex items-center justify-center w-10 h-10 rounded-lg',
              isFlights
                ? 'bg-sky-500/10 text-sky-500'
                : 'bg-violet-500/10 text-violet-500'
            )}
          >
            <Icon className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-zinc-900 dark:text-white">
              {isFlights ? 'Flights' : 'Hotels'}
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              {routeSummary}
            </p>
          </div>
        </div>

        {/* Status Badge */}
        <span
          className={cn(
            'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide border',
            statusBadge.color
          )}
        >
          {status === 'complete' && <Check className="w-3 h-3" />}
          {statusBadge.text}
        </span>
      </div>

      {/* Date info */}
      <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-4">
        {dateSummary}
      </p>

      {/* CTA Button */}
      <button
        onClick={onAction}
        disabled={isDisabled}
        className={cn(
          'w-full flex items-center justify-center gap-2 h-10 rounded-lg',
          'text-sm font-medium transition-all duration-200',
          status === 'complete'
            ? 'bg-emerald-500 text-white hover:bg-emerald-600'
            : isFlights
            ? 'bg-sky-500 text-white hover:bg-sky-600'
            : 'bg-violet-500 text-white hover:bg-violet-600',
          isDisabled && 'opacity-50 cursor-not-allowed'
        )}
      >
        {status === 'loading' ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <ArrowRight className="w-4 h-4" />
        )}
        {ctaText}
      </button>

      {/* Missing data hint */}
      {status === 'pending' && !canSearch && (
        <p className="text-[10px] text-amber-500 mt-2 text-center">
          {isFlights && !origin && 'Add origin • '}
          {!destination && 'Add destination • '}
          {(!startDate || !endDate) && 'Add dates'}
        </p>
      )}
    </div>
  );
});

export default BookingAnchorCard;
