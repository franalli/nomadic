/**
 * PriorityBookingsSection
 *
 * Amber-styled warning section for items that require advance booking.
 * Shows attractions, restaurants, and experiences that sell out quickly.
 */

'use client';

import { AlertTriangle, Clock, ExternalLink,Ticket } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';

interface PriorityItem {
  title: string;
  reason: string;
  advance_notice?: string; // e.g., "2-3 weeks"
  booking_url?: string;
  logic_hook?: string;
}

interface PriorityBookingsSectionProps {
  items: PriorityItem[];
}

export const PriorityBookingsSection = memo(function PriorityBookingsSection({
  items,
}: PriorityBookingsSectionProps) {
  // Filter to only items that need booking
  const bookingItems = items.filter(
    (item) =>
      item.logic_hook?.includes('BOOK') ||
      item.advance_notice ||
      item.booking_url
  );

  if (bookingItems.length === 0) return null;

  return (
    <div
      className={cn(
        'rounded-xl border-2 border-dashed p-4',
        'border-zinc-500/40 bg-zinc-500/5',
        'dark:border-zinc-500/30 dark:bg-zinc-500/10'
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-zinc-500/20">
          <AlertTriangle className="w-4 h-4 text-zinc-500" />
        </div>
        <div>
          <h3 className="font-semibold text-zinc-700 dark:text-zinc-400 text-sm">
            Book in Advance
          </h3>
          <p className="text-[10px] text-zinc-600/70 dark:text-zinc-400/70">
            These experiences sell out quickly
          </p>
        </div>
      </div>

      {/* Items list */}
      <div className="space-y-2">
        {bookingItems.map((item, idx) => (
          <div
            key={idx}
            className={cn(
              'flex items-start gap-3 p-3 rounded-lg',
              'bg-white/60 dark:bg-zinc-900/60',
              'border border-zinc-200/50 dark:border-zinc-500/20'
            )}
          >
            <Ticket className="w-4 h-4 text-zinc-500 mt-0.5 flex-shrink-0" />

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-medium text-zinc-900 dark:text-white truncate">
                  {item.title}
                </h4>
                {item.advance_notice && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium bg-zinc-500/10 text-zinc-600 dark:text-zinc-400">
                    <Clock className="w-2.5 h-2.5" />
                    {item.advance_notice}
                  </span>
                )}
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                {item.reason}
              </p>
            </div>

            {item.booking_url && (
              <a
                href={item.booking_url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  'flex items-center justify-center w-8 h-8 rounded-lg flex-shrink-0',
                  'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400',
                  'hover:bg-zinc-500/20 transition-colors'
                )}
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            )}
          </div>
        ))}
      </div>

      {/* Footer hint */}
      <p className="text-[10px] text-zinc-600/60 dark:text-zinc-400/60 mt-3 text-center">
        Booking links will be available after generating your itinerary
      </p>
    </div>
  );
});

export default PriorityBookingsSection;
