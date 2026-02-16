/**
 * PlanHeader
 *
 * Sticky header for the right-side plan panel.
 * Two variants:
 * 1. Empty (no destination) - Compact bar with progress indicator only
 * 2. Hero (destination exists) - Full image header with title/subtitle
 *
 * Two-mode system: PLANNING + BOOKING
 * - PLANNING: Evolves naturally based on user inputs (destination → dates → itinerary)
 * - BOOKING: Transaction mode with price comparison
 *
 * Progress indicator shows completion within PLANNING mode.
 */

'use client';

import { Loader2 } from 'lucide-react';
import React from 'react';

import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { placeholderImagesForBranch } from '@/lib/placeholders';
import { getStatusPillText } from '@/lib/statusCopyMap';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

export interface PlanHeaderProps {
  destinationCard?: DestinationCard;
  isGenerating?: boolean;
  /** Fallback title from tripInputs if destinationCard not available */
  fallbackTitle?: string;
  /** PlanViewState for accurate step tracking */
  planViewState?: string;
  /** Whether expanding to itinerary (S3 generation) */
  isExpandingItinerary?: boolean;
  /** Trip inputs for displaying summary pills in S1+ */
  tripInputs?: DocumentTripInputs;
  /** Handler to open a sheet for editing trip inputs */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Whether streaming/generation is in progress (disables pills) */
  isStreaming?: boolean;
  /** Whether header is collapsed (mobile scroll state) */
  isCollapsed?: boolean;
}

export function PlanHeader({
  destinationCard,
  isGenerating = false,
  fallbackTitle,
  planViewState = 'S0_BOOTSTRAP',
  isExpandingItinerary = false,
  tripInputs: propTripInputs,
  onOpenSheet,
  isStreaming = false,
  isCollapsed = false,
}: PlanHeaderProps) {
  // FIX: Header needs to update immediately when dates change in store
  const tripInputs = useTripInputsWithFallback(propTripInputs);
  // Determine variant based on whether we have a destination
  const title = destinationCard?.title || fallbackTitle || '';
  const hasDestination = Boolean(title);
  // Gate hero image layer on both title AND image - prevents flash during image load
  const showHeroImage = hasDestination && Boolean(destinationCard?.image_url);
  // Status pill text for progress indicator
  const statusPillText = getStatusPillText(isGenerating, isExpandingItinerary);

  // Get image URL: always use placeholder if destination exists (never grey gradient)
  const imageUrl = React.useMemo(() => {
    if (destinationCard?.image_url) {
      return destinationCard.image_url;
    }
    // Always use placeholder for known destination - never fall back to grey
    if (title) {
      const placeholders = placeholderImagesForBranch({ destination: title });
      return placeholders[0] || '/assets/default-destination.jpg';
    }
    return null;
  }, [destinationCard?.image_url, title]);

  // Check if we should show pills (S1+ with tripInputs and handler)
  const showPills =
    planViewState !== 'S0_BOOTSTRAP' && tripInputs && onOpenSheet;

  // Format date range for collapsed view (must be before early return to maintain hook order)
  const startDate = tripInputs?.start_date;
  const endDate = tripInputs?.end_date;
  const dateRangeText = React.useMemo(() => {
    if (!startDate) return null;
    const start = new Date(startDate);
    const startFormatted = start.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
    if (endDate) {
      const end = new Date(endDate);
      const endFormatted = end.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      });
      return `${startFormatted} - ${endFormatted}`;
    }
    return startFormatted;
  }, [startDate, endDate]);

  // Shared hero height - viewport-height relative so it scales with screen height, not width
  // 13" (800px h) → 200px | 15" (900px h) → 225px | 27" (1440px h) → capped at 280px
  const HERO_HEIGHT = 'h-[clamp(180px,25vh,280px)]';

  // COLLAPSED STATE: Compact header bar when scrolled
  if (isCollapsed) {
    return (
      <div className="relative flex-shrink-0">
        <div className="border-b border-border bg-secondary dark:bg-card dark:border-border/60">
          <div className="flex items-center justify-between px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">
                {title || 'Plan your trip'}
              </span>
              {dateRangeText && (
                <span className="text-xs text-muted-foreground">
                  ({dateRangeText})
                </span>
              )}
            </div>

            {/* Status pill - shown during generation */}
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

  // HERO STATE: Two variants depending on whether destination image is ready
  // Without image: Living Topography with centered prompt
  // With image: Vertical stack — clean image, text below on app bg
  if (!showHeroImage) {
    // Pre-destination: Topo base with setup prompt
    return (
      <div className="relative flex-shrink-0">
        <div className={`relative ${HERO_HEIGHT} overflow-y-clip overflow-x-visible`}>
          <div
            className="absolute inset-0 z-10"
            style={{
              backgroundColor: 'hsl(var(--background))',
              maskImage:
                'radial-gradient(ellipse at center, black 40%, transparent 100%)',
              WebkitMaskImage:
                'radial-gradient(ellipse at center, black 40%, transparent 100%)',
            }}
          >
            <div
              className="absolute inset-0 z-0"
              style={{
                maskImage:
                  'radial-gradient(circle at center, black 0%, transparent 70%)',
                WebkitMaskImage:
                  'radial-gradient(circle at center, black 0%, transparent 70%)',
              }}
            >
              <div
                className="absolute inset-0 animate-topo-drift opacity-[0.12] dark:opacity-[0.18]"
                style={{
                  maskImage: 'url("/assets/contours.svg")',
                  WebkitMaskImage: 'url("/assets/contours.svg")',
                  maskSize: '600px',
                  WebkitMaskSize: '600px',
                  maskRepeat: 'repeat',
                  WebkitMaskRepeat: 'repeat',
                  maskPosition: '0% 0%',
                  WebkitMaskPosition: '0% 0%',
                  willChange: '-webkit-mask-position, mask-position',
                }}
              >
                <div className="absolute inset-0 bg-zinc-900 dark:bg-white" />
              </div>
            </div>
            <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(16,185,129,0.06)_0%,_transparent_55%)] dark:bg-[radial-gradient(ellipse_at_center,_rgba(16,185,129,0.12)_0%,_transparent_55%)] z-0" />
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4 pb-6 z-20">
              <h1 className="text-2xl md:text-3xl font-semibold tracking-tight drop-shadow-sm text-black dark:text-white dark:drop-shadow-lg">
                Build Your Itinerary
              </h1>
              <p className="mt-2 text-xs uppercase tracking-[0.25em] font-medium text-emerald-700 dark:text-emerald-400/80">
                Intelligent Trip Architect
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Post-destination: Compact image + pills in vertical flow
  return (
    <div className="relative flex-shrink-0">
      {/* Clean hero image — no overlay, no gradient */}
      <div className={cn(
        'mx-4 mt-4 rounded-2xl overflow-hidden shadow-2xl transition-all duration-300',
        isGenerating || isExpandingItinerary
          ? 'animate-pulse opacity-80 ring-1 ring-emerald-500/20 dark:ring-emerald-500/30'
          : 'ring-1 ring-black/10 dark:ring-white/10'
      )}>
        {imageUrl && (
          <img
            src={imageUrl}
            alt={title}
            className="w-full max-h-[15vh] min-h-[120px] object-cover"
          />
        )}
      </div>

      {/* Pills ARE the summary — no title, no subtitle, no specialist pills */}
      {showPills && (
        <div className="px-6 pt-5 pb-4">
          <TripSummaryPills
            tripInputs={tripInputs}
            onOpenSheet={onOpenSheet}
            disabled={isStreaming}
            variant="default"
            readOnlyExceptDestination={false}
          />
        </div>
      )}
    </div>
  );
}

export default PlanHeader;
