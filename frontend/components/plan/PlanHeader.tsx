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

import { ArrowRight, Loader2 } from 'lucide-react';
import React from 'react';

import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { placeholderImagesForBranch } from '@/lib/placeholders';
import { getStatusPillText } from '@/lib/statusCopyMap';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

export interface PlanHeaderProps {
  destinationCard?: DestinationCard;
  currentStage: 'bootstrap' | 'structure' | 'strategy' | 'itinerary';
  isGenerating?: boolean;
  /** Fallback title from tripInputs if destinationCard not available */
  fallbackTitle?: string;
  /** PlanViewState for accurate step tracking */
  planViewState?: string;
  /** Whether user has set dates */
  hasDates?: boolean;
  /** Whether expanding to itinerary (S3 generation) */
  isExpandingItinerary?: boolean;
  /** Current backend sub-stage (structure, strategy, itinerary, deals) */
  currentSubStage?: string | null;
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
  currentStage: _currentStage,
  isGenerating = false,
  fallbackTitle,
  planViewState = 'S0_BOOTSTRAP',
  hasDates: _hasDates = false,
  isExpandingItinerary = false,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  currentSubStage: _currentSubStage,
  tripInputs: propTripInputs,
  onOpenSheet,
  isStreaming = false,
  isCollapsed = false,
}: PlanHeaderProps) {
  // FIX: Header needs to update immediately when dates change in store
  const tripInputs = useTripInputsWithFallback(propTripInputs);

  // currentStage kept for backwards compatibility but planViewState is preferred
  void _currentStage;
  // hasDates reserved for future use
  void _hasDates;
  // Determine variant based on whether we have a destination
  const title = destinationCard?.title || fallbackTitle || '';
  const hasDestination = Boolean(title);
  // Gate hero image layer on both title AND image - prevents flash during image load
  const showHeroImage = hasDestination && Boolean(destinationCard?.image_url);
  // Subtitle: Show route when origin is set, otherwise hide (date is redundant with chip)
  const origin = tripInputs?.origin;
  const subtitle = origin ? `${origin} → ${title}` : null;

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

  // HERO STATE: Layer-stacked header with cross-fade transition
  // Layer 1: Living Topography (always rendered as base)
  // Layer 2: Destination Image (fades in when destination exists)
  return (
    <div className="relative flex-shrink-0">
      {/* Hero container - shared height for both states */}
      {/* overflow-x-visible allows pills to scroll, overflow-y-clip contains topo animation */}
      <div className={`relative ${HERO_HEIGHT} overflow-y-clip overflow-x-visible`}>
        {/* LAYER 1: Living Topography Base with Full Edge Feathering */}
        {/* Radial mask dissolves ALL edges (top/bottom/left/right) into global bg */}
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
          {/* SPOTLIGHT: Radial fade limits pattern visibility to center */}
          <div
            className="absolute inset-0 z-0"
            style={{
              maskImage:
                'radial-gradient(circle at center, black 0%, transparent 70%)',
              WebkitMaskImage:
                'radial-gradient(circle at center, black 0%, transparent 70%)',
            }}
          >
            {/* PATTERN LAYER: The actual moving lines */}
            {/* Light mode: dark ink lines (stronger). Dark mode: white glow lines */}
            <div
              className="absolute inset-0 animate-topo-drift opacity-[0.12] dark:opacity-[0.18]"
              style={{
                maskImage: 'url("/assets/contours.svg")',
                WebkitMaskImage: 'url("/assets/contours.svg")',
                maskSize: '600px',
                WebkitMaskSize: '600px',
                maskRepeat: 'repeat',
                WebkitMaskRepeat: 'repeat',
                // Initial position + will-change for iOS Safari animation support
                maskPosition: '0% 0%',
                WebkitMaskPosition: '0% 0%',
                willChange: '-webkit-mask-position, mask-position',
              }}
            >
              {/* Solid color layer - different for light/dark */}
              <div className="absolute inset-0 bg-zinc-900 dark:bg-white" />
            </div>
          </div>

          {/* Emerald glow - the "light source" behind the pattern */}
          {/* Reduced in light mode, prominent in dark mode */}
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(16,185,129,0.06)_0%,_transparent_55%)] dark:bg-[radial-gradient(ellipse_at_center,_rgba(16,185,129,0.12)_0%,_transparent_55%)] z-0" />

          {/* Setup prompt text - fades out when destination image is ready */}
          <div
            className={`absolute inset-0 flex flex-col items-center justify-center text-center px-4 pb-6 transition-opacity duration-500 z-20 ${
              showHeroImage ? 'opacity-0' : 'opacity-100'
            }`}
          >
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight drop-shadow-sm text-black dark:text-white dark:drop-shadow-lg">
              Build Your Itinerary
            </h1>
            <p className="mt-2 text-xs uppercase tracking-[0.25em] font-medium text-emerald-700 dark:text-emerald-400/80">
              Intelligent Trip Architect
            </p>
          </div>
        </div>

        {/* LAYER 2: Destination Image - "Glossy Postcard" style */}
        {/* Physical photo sitting on the architect's desk - rounded, shadowed, crisp */}
        {/* Only shows when image is loaded - prevents flash during image fetch */}
        <div
          className={`absolute inset-4 z-20 transition-all duration-700 ${
            showHeroImage ? 'opacity-100 scale-100' : 'opacity-0 scale-95 pointer-events-none'
          }`}
        >
          <div className="relative h-full w-full rounded-2xl overflow-hidden shadow-2xl ring-1 ring-black/10 dark:ring-white/10">
            {imageUrl && (
              <img
                src={imageUrl}
                alt={title}
                className="absolute inset-0 h-full w-full object-cover"
              />
            )}

            {/* Subtle scrim for text readability - z-10 so pills can be above */}
            <div className="absolute inset-0 z-10 bg-gradient-to-t from-black/50 via-black/10 to-transparent" />

            {/* Destination content overlay - title/subtitle only */}
            <div className="absolute inset-0 z-10 flex flex-col justify-end p-5 pb-14">
              <h2 className="text-xl font-semibold text-white drop-shadow-md">{title}</h2>
              {subtitle && (
                <p className="mt-0.5 text-sm text-white/90 drop-shadow-sm flex items-center gap-1.5">
                  {/* Parse subtitle and replace arrow characters with icon */}
                  {subtitle.split(/[→\->]+/).map((part, i, arr) => (
                    <span key={i} className="flex items-center gap-1.5">
                      {part.trim()}
                      {i < arr.length - 1 && (
                        <ArrowRight className="w-3 h-3 text-white/70" />
                      )}
                    </span>
                  ))}
                </p>
              )}
            </div>

            {/* Pills - INSIDE the postcard, above gradient overlay */}
            {/* Frosted glass strip separates chips from image for readability */}
            {/* When in S3 (itinerary exists), make pills read-only except destination for demo safety */}
            {showPills && (
              <div className="absolute bottom-3 left-4 right-4 z-20 backdrop-blur-md bg-black/30 rounded-xl px-3 py-2 flex items-center gap-2 flex-wrap">
                <TripSummaryPills
                  tripInputs={tripInputs}
                  onOpenSheet={onOpenSheet}
                  disabled={isStreaming}
                  variant="onImage"
                  readOnlyExceptDestination={false}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default PlanHeader;
