/**
 * PlanHeader
 *
 * Sticky header for the right-side plan panel.
 * Two variants:
 * 1. Empty (no destination) - Compact bar with stepper only
 * 2. Hero (destination exists) - Full image header with title/subtitle
 *
 * Single progress system: Setup • Plan • Book
 * - Amber = active
 * - Green = completed only
 * - Gray = locked
 */

'use client';

import { ChevronLeft, Loader2 } from 'lucide-react';
import React from 'react';

import { GlassCommandBar } from '@/components/plan/GlassCommandBar';
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
  /** Callback when Setup stage is clicked (navigate back to setup/config) */
  onSetupClick?: () => void;
  /** Callback when Plan stage is clicked (navigate to plan view) */
  onPlanClick?: () => void;
  /** Callback when Book stage is clicked (navigate to booking view) */
  onBookClick?: () => void;
  /** Whether user has minimum selections to enable Book stage */
  hasMinimumSelections?: boolean;
  /** Whether header is collapsed (mobile scroll state) */
  isCollapsed?: boolean;
  /** Currently active view (for view-based navigation) */
  activeView?: 'setup' | 'plan' | 'book';
  /** Whether Setup view is accessible (not locked after planning starts) */
  canViewSetup?: boolean;
  /** Whether Plan view is unlocked (destination exists) */
  canViewPlan?: boolean;
  /** Whether Book view is unlocked (tiles exist) */
  canViewBook?: boolean;
}

/** Step key type for navigation callbacks */
type StepKey = 'setup' | 'plan' | 'book';

export function PlanHeader({
  destinationCard,
  currentStage: _currentStage,
  isGenerating = false,
  fallbackTitle,
  planViewState = 'S0_BOOTSTRAP',
  hasDates: _hasDates = false,
  isExpandingItinerary = false,
  currentSubStage: _currentSubStage,
  tripInputs: propTripInputs,
  onOpenSheet,
  isStreaming = false,
  onSetupClick,
  onPlanClick,
  onBookClick,
  hasMinimumSelections = false,
  isCollapsed = false,
  activeView,
  canViewSetup = true,
  canViewPlan = false,
  canViewBook = false,
}: PlanHeaderProps) {
  // FIX: Header needs to update immediately when dates change in store
  const tripInputs = useTripInputsWithFallback(propTripInputs);

  // currentStage kept for backwards compatibility but planViewState is preferred
  void _currentStage;
  // hasDates reserved for future use
  void _hasDates;
  // hasMinimumSelections reserved for future Book view gating
  void hasMinimumSelections;
  // Determine variant based on whether we have a destination
  const title = destinationCard?.title || fallbackTitle || '';
  const hasDestination = Boolean(title);
  const subtitle = destinationCard?.subtitle;

  // Handle step clicks - map step key to appropriate callback
  const handleStepClick = React.useCallback(
    (step: StepKey) => {
      switch (step) {
        case 'setup':
          onSetupClick?.();
          break;
        case 'plan':
          onPlanClick?.();
          break;
        case 'book':
          // Navigation to Book view - canViewBook already gates this in StageStepper
          onBookClick?.();
          break;
      }
    },
    [onSetupClick, onPlanClick, onBookClick]
  );

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

  // Shared hero height for both states - prevents layout shift on transition
  const HERO_HEIGHT = 'h-40 lg:h-56';

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
              <div className="flex items-center gap-1.5 rounded-full bg-amber-500/15 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-400 dark:bg-amber-500/10">
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
      <div className={`relative ${HERO_HEIGHT} overflow-hidden`}>
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
              }}
            >
              {/* Solid color layer - different for light/dark */}
              <div className="absolute inset-0 bg-zinc-900 dark:bg-white" />
            </div>
          </div>

          {/* Emerald glow - the "light source" behind the pattern */}
          {/* Reduced in light mode, prominent in dark mode */}
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(16,185,129,0.06)_0%,_transparent_55%)] dark:bg-[radial-gradient(ellipse_at_center,_rgba(16,185,129,0.12)_0%,_transparent_55%)] z-0" />

          {/* Setup prompt text - fades out when destination exists */}
          <div
            className={`absolute inset-0 flex flex-col items-center justify-center text-center px-4 pb-6 transition-opacity duration-500 z-20 ${
              hasDestination ? 'opacity-0' : 'opacity-100'
            }`}
          >
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight drop-shadow-sm text-black dark:text-white dark:drop-shadow-lg">
              Where to next?
            </h1>
            <p className="mt-2 text-xs uppercase tracking-[0.25em] font-medium text-emerald-700 dark:text-emerald-400/80">
              AI-Powered Trip Architect
            </p>
          </div>
        </div>

        {/* LAYER 2: Destination Image - "Glossy Postcard" style */}
        {/* Physical photo sitting on the architect's desk - rounded, shadowed, crisp */}
        <div
          className={`absolute inset-4 z-20 transition-all duration-700 ${
            hasDestination ? 'opacity-100 scale-100' : 'opacity-0 scale-95 pointer-events-none'
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

            {/* Subtle scrim for text readability - lighter than before */}
            <div className="absolute inset-0 bg-gradient-to-t from-black/50 via-black/10 to-transparent" />

            {/* Destination content overlay */}
            <div className="absolute inset-0 flex flex-col justify-end p-5">
              <h2 className="text-xl font-semibold text-white drop-shadow-md">{title}</h2>
              {subtitle && (
                <p className="mt-0.5 text-sm text-white/90 drop-shadow-sm">{subtitle}</p>
              )}
              {/* Trip summary pills - only in S1+ (use onImage variant for hero) */}
              {showPills && (
                <div className="mt-3">
                  <TripSummaryPills
                    tripInputs={tripInputs}
                    onOpenSheet={onOpenSheet}
                    disabled={isStreaming}
                    variant="onImage"
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Floating Glass Command Bar - Desktop only (mobile uses bottom nav) */}
      <div className="hidden md:block">
        <GlassCommandBar
          activeView={activeView ?? 'setup'}
          canViewSetup={canViewSetup}
          canViewPlan={canViewPlan}
          canViewBook={canViewBook}
          isGenerating={isGenerating}
          onNavigate={(view) => handleStepClick(view as 'setup' | 'plan' | 'book')}
        />
      </div>

      {/* THE ARCHITECT INSTRUCTION LAYER - Setup mode only */}
      {/* Console-style status indicator for the empty/setup state */}
      {/* Hidden in Plan/Book modes - the Hero Image IS the confirmation */}
      {activeView === 'setup' && (
        <div className="mt-8 flex flex-col items-center justify-center space-y-2 animate-in fade-in slide-in-from-bottom-2 duration-700 delay-500">
          <div className="flex items-center gap-3 group cursor-default">
            {/* The Pointer (Animated '<<') */}
            <div className="flex text-zinc-900 dark:text-emerald-400 animate-pulse">
              <ChevronLeft className="w-3 h-3 -mr-1.5" />
              <ChevronLeft className="w-3 h-3" />
            </div>
            {/* The System Text - Jet Black (Light) / Neon Terminal (Dark) */}
            <p className="font-mono text-[10px] uppercase tracking-[0.25em] select-none font-semibold text-zinc-900 dark:text-emerald-400">
              {!hasDestination ? 'Awaiting Input_' : 'Parameters Updated_'}
            </p>
            {/* The Blinking Cursor */}
            <div className="w-1.5 h-2.5 bg-zinc-900 dark:bg-emerald-400 animate-blink" />
          </div>
        </div>
      )}

      {/* Spacer to accommodate floating command bar */}
      <div className="h-8" />
    </div>
  );
}

export default PlanHeader;
