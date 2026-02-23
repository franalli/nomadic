'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * PlanHeader
 *
 * Sticky header for the right-side plan panel.
 * Plan panel shows chips only — hero image lives in ChatPanel.
 *
 * Two-mode system: PLANNING + BOOKING
 * - PLANNING: Evolves naturally based on user inputs (destination → dates → itinerary)
 * - BOOKING: Transaction mode with price comparison
 */


import { Loader2 } from 'lucide-react';
import React from 'react';

import { isBootstrap } from '@/components/plan/planStateHelpers';
import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { getStatusPillText } from '@/lib/statusCopyMap';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

interface PlanHeaderProps {
  isGenerating?: boolean;
  /** Fallback title from tripInputs if destinationCard not available */
  fallbackTitle?: string;
  /** PlanViewState for accurate step tracking */
  planViewState?: string;
  /** Whether expanding to itinerary (S3 generation) */
  isExpandingItinerary?: boolean;
  /** Trip inputs for displaying summary pills in S1+ */
  tripInputs?: DocumentTripInputs;
  /** Day cards for deriving scheduled activity counts in pills */
  dayCards?: DayCard[];
  /** Handler to open a sheet for editing trip inputs */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Whether streaming/generation is in progress (disables pills) */
  isStreaming?: boolean;
  /** Whether header is collapsed (mobile scroll state) */
  isCollapsed?: boolean;
}

export function PlanHeader({
  isGenerating = false,
  fallbackTitle,
  planViewState = 'S0_BOOTSTRAP',
  isExpandingItinerary = false,
  tripInputs: propTripInputs,
  dayCards,
  onOpenSheet,
  isStreaming = false,
  isCollapsed = false,
}: PlanHeaderProps) {
  const tripInputs = useTripInputsWithFallback(propTripInputs);
  const title = fallbackTitle || tripInputs?.destination || '';
  const statusPillText = getStatusPillText(isGenerating, isExpandingItinerary);

  // Check if we should show pills (S1+ with tripInputs and handler)
  const showPills =
    !isBootstrap(planViewState as PlanViewState) && tripInputs && onOpenSheet;

  // Format date range for collapsed view (hooks must be called unconditionally)
  const startDate = tripInputs?.start_date;
  const endDate = tripInputs?.end_date;
  const dateRangeText = React.useMemo(() => {
    if (!startDate) return null;
    const start = new Date(startDate);
    const startFormatted = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    if (endDate) {
      const end = new Date(endDate);
      const endFormatted = end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      return `${startFormatted} - ${endFormatted}`;
    }
    return startFormatted;
  }, [startDate, endDate]);

  // COLLAPSED STATE: Compact header bar when scrolled
  if (isCollapsed) {
    return (
      <div className="relative flex-shrink-0">
        <div className="border-b border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950/95 backdrop-blur-xl">
          <div className="flex items-center justify-between px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-zinc-900 dark:text-white">
                {title || 'Plan your trip'}
              </span>
              {dateRangeText && (
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  ({dateRangeText})
                </span>
              )}
            </div>
            {statusPillText && (
              <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1 text-xs text-emerald-600 dark:text-emerald-400 dark:bg-emerald-500/10">
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>{statusPillText}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Plan panel header: chips only, no hero image (hero lives in ChatPanel)
  if (!showPills) return null;

  return (
    <div className={cn(
      'relative flex-shrink-0 px-4 pt-3 pb-1.5',
      (isGenerating || isExpandingItinerary) && 'opacity-80',
    )}>
      <TripSummaryPills
        tripInputs={tripInputs}
        dayCards={dayCards}
        onOpenSheet={onOpenSheet}
        disabled={isStreaming}
        variant="default"
        readOnlyExceptDestination={false}
      />
    </div>
  );
}

export default PlanHeader;
