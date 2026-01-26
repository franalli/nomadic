'use client';

import { memo } from 'react';

import { BookingSection, type BookingSectionProps } from '@/components/plan/BookingSection';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface BookViewProps extends BookingSectionProps {
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * BookView - Standalone wrapper for BookingSection for the mobile Book tab.
 *
 * Renders the booking tiles/options in a full-screen mobile view.
 * Receives the same props as BookingSection.
 */
function BookViewInner({
  state,
  tiles,
  generation,
  hasStrategyContent,
  savedTileIds,
  onSaveTile,
  onOpenSheet,
  className,
}: BookViewProps) {
  return (
    <div className={cn('flex flex-col min-h-full', className)}>
      <BookingSection
        state={state}
        tiles={tiles}
        generation={generation}
        hasStrategyContent={hasStrategyContent}
        savedTileIds={savedTileIds}
        onSaveTile={onSaveTile}
        onOpenSheet={onOpenSheet}
      />
    </div>
  );
}

export const BookView = memo(BookViewInner);
