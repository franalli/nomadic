/**
 * MobileSetupCollapsedHeader
 *
 * Compact sticky header shown in Setup phase when user scrolls past threshold.
 * Collapses the full hero + chip stack into a condensed glass bar.
 *
 * Design (from design-system.md Section 11.1):
 * ┌────────────────────────────────────────────┐
 * │  Dubai · Jan 29 - Feb 4            [tune]  │  ← h-14 glass bar
 * └────────────────────────────────────────────┘
 *
 * - Shows destination + dates in a single condensed line
 * - "tune" icon (Settings2) expands back to full chip row
 * - Glass background with blur
 */

'use client';

import { motion } from 'framer-motion';
import { ChevronDown, Settings2 } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

interface MobileSetupCollapsedHeaderProps {
  tripInputs?: DocumentTripInputs;
  dateRange?: string;
  /** Called when user taps to expand back to full view */
  onExpand?: () => void;
  className?: string;
}

function MobileSetupCollapsedHeaderInner({
  tripInputs,
  dateRange,
  onExpand,
  className,
}: MobileSetupCollapsedHeaderProps) {
  // Build summary text: "Destination · Dates" or fallback
  const destination = tripInputs?.destination;
  const summaryParts: string[] = [];

  if (destination) {
    // Extract just the city name if it's a long format like "Dubai, United Arab Emirates"
    const cityName = destination.split(',')[0].trim();
    summaryParts.push(cityName);
  }

  if (dateRange) {
    summaryParts.push(dateRange);
  }

  // Fallback if nothing is set yet
  const summaryText = summaryParts.length > 0
    ? summaryParts.join(' · ')
    : 'Where to next?';

  // Show "incomplete" state indicator when not all required fields are set
  const isIncomplete = !destination || !dateRange;

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className={cn(
        // Positioning: sticky at top, full width bleed
        'sticky top-0 z-40',
        '-mx-4 -mt-4 mb-2',
        'w-[calc(100%+2rem)]',
        // Height per spec: h-14 (56px)
        'h-14 px-4',
        // Glassmorphism
        'bg-white/80 dark:bg-zinc-900/80 backdrop-blur-md',
        'border-b border-zinc-200 dark:border-white/5',
        // Flex layout
        'flex items-center justify-between',
        'transition-all duration-300',
        className
      )}
    >
      {/* Left: Summary text */}
      <div className="flex items-center gap-2 min-w-0 flex-1">
        {/* Status dot - pulsing when incomplete */}
        <div
          className={cn(
            'w-2 h-2 rounded-full flex-shrink-0',
            isIncomplete
              ? 'bg-zinc-400 dark:bg-zinc-600'
              : 'bg-emerald-500 animate-pulse'
          )}
        />
        {/* Summary text */}
        <span
          className={cn(
            'text-sm font-semibold truncate',
            isIncomplete
              ? 'text-zinc-500 dark:text-zinc-400'
              : 'text-zinc-900 dark:text-white'
          )}
        >
          {summaryText}
        </span>
      </div>

      {/* Right: Expand/Tune button */}
      <button
        type="button"
        onClick={onExpand}
        className={cn(
          'flex items-center gap-1.5 px-3 py-2 rounded-lg flex-shrink-0',
          'text-zinc-500 dark:text-zinc-400',
          'hover:bg-zinc-100 dark:hover:bg-white/5',
          'active:scale-95',
          'transition-all duration-150'
        )}
        aria-label="Expand trip settings"
      >
        <Settings2 className="w-4 h-4" />
        <ChevronDown className="w-3 h-3" />
      </button>
    </motion.div>
  );
}

export const MobileSetupCollapsedHeader = memo(MobileSetupCollapsedHeaderInner);

export default MobileSetupCollapsedHeader;
