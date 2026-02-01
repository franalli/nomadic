/**
 * S3ItineraryView
 *
 * Itinerary ready state - shows day cards and overview.
 * Day cards are collapsed by default, max 1 expanded at a time.
 */

'use client';

import { motion } from 'framer-motion';
import { ArrowRight, ChevronUp, Map } from 'lucide-react';
import React, { useCallback, useState } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapLayerFilter } from '@/components/map/MapLayerFilter';
import { BookingDrawer } from '@/components/plan/booking/BookingDrawer';
import { DestinationMapPlaceholder } from '@/components/plan/DestinationMapPlaceholder';
import { TimelineSkeleton } from '@/components/plan/timeline/TimelineSkeleton';
import { TimelineThread } from '@/components/plan/TimelineThread';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent } from '@/components/ui/sheet';
import { useMapSync } from '@/hooks/useMapSync';
import { getDestinationCoords } from '@/lib/destination-coords';
import { cn } from '@/lib/utils';
import type {
  DestinationCard,
  ItineraryOverview,
  PlanViewModel,
} from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

interface S3ItineraryViewProps {
  viewModel: PlanViewModel;
  /** Kept for context but not rendered (header owns destination display) */
  destinationCard?: DestinationCard;
  /** Enable Tetris-style staggered animation on initial render */
  animateEntrance?: boolean;
  /** Callback to finalize plan and navigate to Book view */
  onFinalize?: () => void;
  /** Whether finalization is in progress */
  isFinalizing?: boolean;
  /** Whether itinerary is being generated */
  isGenerating?: boolean;
  // === NEW: Booking Integration Props ===
  /** Available tiles for booking drawer */
  tiles?: Record<string, Tile>;
  /** Set of saved tile IDs */
  savedTileIds?: Set<string>;
  /** Callback when user saves a tile */
  onSaveTile?: (tile: Tile) => void;
  /** Callback when user unassigns a tile from a block */
  onUnassignTile?: (blockId: string) => void;
}

function OverviewCard({ overview }: { overview: ItineraryOverview }) {
  return (
    <div className="bg-zinc-800/30 rounded-lg border border-zinc-700/30 p-3">
      <div className="flex items-center gap-2 text-xs text-zinc-400">
        <span>{overview.duration_label}</span>
        <span className="text-zinc-600">-</span>
        <span>{overview.base_structure}</span>
        <span className="text-zinc-600">-</span>
        <span>{overview.activity_density}</span>
      </div>
    </div>
  );
}

export function S3ItineraryView({
  viewModel,
  destinationCard,
  animateEntrance = true,
  onFinalize,
  isFinalizing = false,
  isGenerating = false,
  // Booking integration props
  tiles,
  savedTileIds,
  onSaveTile,
  onUnassignTile,
}: S3ItineraryViewProps) {
  const { day_cards = [], itinerary_overview, itinerary_assumptions, strategy_sections } = viewModel;
  const [expandedDay, setExpandedDay] = React.useState<number | null>(null);

  // Mobile bottom sheet expansion state
  const [isMobileExpanded, setIsMobileExpanded] = React.useState(false);

  // Booking drawer state
  const [bookingDrawerCategory, setBookingDrawerCategory] = useState<'hotel' | 'flight' | 'activity' | null>(null);

  // Mobile full-screen map state
  const [isMobileMapOpen, setIsMobileMapOpen] = useState(false);

  // === Map-Itinerary Two-Way Sync ===
  const {
    mapItems,
    activeItemId: activeBlockId,
    hoveredDay,
    setHoveredDay,
    handleMarkerClick,
    routeGeoJson,
    visibleLayers,
    toggleLayer,
    showAllLayers,
    availableTypes,
    hasItems: hasMapItems,
  } = useMapSync({
    dayCards: day_cards,
    strategySections: strategy_sections,
    mode: 'plan',
  });

  // Get destination coordinates from hardcoded lookup (MVP)
  const destinationCoords = React.useMemo(() => {
    return getDestinationCoords(destinationCard?.title);
  }, [destinationCard?.title]);

  // Handle opening booking drawer
  const handleOpenBookingDrawer = useCallback((category: 'hotel' | 'flight' | 'activity') => {
    setBookingDrawerCategory(category);
  }, []);

  // Handle closing booking drawer
  const handleCloseBookingDrawer = useCallback(() => {
    setBookingDrawerCategory(null);
  }, []);

  // Track if we've already animated (only animate once on mount)
  const [hasAnimated, setHasAnimated] = React.useState(false);
  const shouldAnimate = animateEntrance && !hasAnimated;

  React.useEffect(() => {
    if (animateEntrance && day_cards.length > 0) {
      // Mark as animated after initial render
      const timer = setTimeout(() => setHasAnimated(true), 1500);
      return () => clearTimeout(timer);
    }
  }, [animateEntrance, day_cards.length]);

  // Shared content for timeline
  const timelineContent = (
    <>
      {/* Overview */}
      {itinerary_overview && <OverviewCard overview={itinerary_overview} />}

      {/* Day cards - Timeline Thread with "beads on string" visualization */}
      {day_cards.length > 0 ? (
        <motion.div
          initial={shouldAnimate ? { opacity: 0 } : false}
          animate={shouldAnimate ? { opacity: 1 } : false}
          transition={{ duration: 0.5 }}
        >
          <TimelineThread
            dayCards={day_cards}
            expandedDay={expandedDay}
            onDayClick={(dayNumber) => setExpandedDay(expandedDay === dayNumber ? null : dayNumber)}
            showPriceEstimates={true}
            activeBlockId={activeBlockId}
            // S3 Itinerary View props
            useRichBlocks={true}
            onDayHover={setHoveredDay}
            onOpenBookingDrawer={handleOpenBookingDrawer}
            onUnassignTile={onUnassignTile}
            savedTileIds={savedTileIds}
          />
        </motion.div>
      ) : (
        /* Show skeleton while itinerary is being generated */
        <TimelineSkeleton />
      )}

      {/* THE BRIDGE: The only path to Book tab - always shown */}
      <motion.div
        className="mt-12 mb-8 p-8 border border-dashed border-border/50 rounded-xl bg-muted/30 text-center"
        initial={shouldAnimate ? { opacity: 0, y: 20 } : false}
        animate={shouldAnimate ? { opacity: 1, y: 0 } : false}
        transition={{ delay: 0.9 }}
      >
        <h3 className="text-lg font-medium mb-2">
          {day_cards.length > 0 ? 'Itinerary Looks Good?' : 'Ready to Continue?'}
        </h3>
        <p className="text-sm text-muted-foreground mb-6">
          {day_cards.length > 0
            ? 'Lock this plan to see real-time availability and prices.'
            : 'Proceed to view booking options and finalize your trip.'}
        </p>
        <Button
          onClick={onFinalize}
          disabled={isFinalizing}
          size="lg"
          className="gap-2"
        >
          {isFinalizing ? (
            <>Scanning best rates...</>
          ) : (
            <>
              Finalize & Unlock Booking
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </Button>
      </motion.div>

      {/* Assumptions (collapsed summary) */}
      {itinerary_assumptions && itinerary_assumptions.assumptions.length > 0 && (
        <motion.div
          className="bg-zinc-800/20 rounded-lg p-3 border border-zinc-700/20"
          initial={shouldAnimate ? { opacity: 0 } : false}
          animate={shouldAnimate ? { opacity: 1 } : false}
          transition={{ delay: 0.8 }}
        >
          <p className="text-xs text-zinc-500 mb-1">Assumptions</p>
          <p className="text-xs text-zinc-400">
            {itinerary_assumptions.assumptions[0]}
            {itinerary_assumptions.assumptions.length > 1 && (
              <span className="text-zinc-600">
                {' '}
                +{itinerary_assumptions.assumptions.length - 1} more
              </span>
            )}
          </p>
        </motion.div>
      )}
    </>
  );

  // Compute map center: use destination coords if available, otherwise fallback
  const mapCenter = React.useMemo(() => {
    if (destinationCoords) {
      return { lng: destinationCoords[0], lat: destinationCoords[1], zoom: 11 };
    }
    // Fallback to first map item's coordinates if available
    if (mapItems.length > 0) {
      return { lat: mapItems[0].coordinates.lat, lng: mapItems[0].coordinates.lng, zoom: 11 };
    }
    // Default fallback (Dubai)
    return { lat: 25.2048, lng: 55.2708, zoom: 10 };
  }, [destinationCoords, mapItems]);

  // Map content (shared between desktop and mobile)
  // Static mode (no POIs): non-interactive, clean UI with just destination pin
  // Interactive mode (with POIs): full scrollytelling experience
  const mapContent = hasMapItems || destinationCoords ? (
    <div className="relative h-full">
      <InteractiveMap
        items={mapItems}
        activeItemId={activeBlockId}
        defaultCenter={mapCenter}
        onMarkerClick={handleMarkerClick}
        routeGeoJson={routeGeoJson}
        visibleLayers={visibleLayers}
        highlightedDay={hoveredDay}
        interactive={hasMapItems} // Static when no POIs, interactive when there are
        showAttribution={false} // Clean UI for MVP
      />
      {/* Layer filter - positioned at top-left of map (only when interactive) */}
      {hasMapItems && availableTypes.length > 1 && (
        <div className="absolute top-3 left-3 z-10">
          <MapLayerFilter
            visibleLayers={visibleLayers}
            onToggle={toggleLayer}
            availableTypes={availableTypes}
            onShowAll={showAllLayers}
          />
        </div>
      )}
    </div>
  ) : (
    <DestinationMapPlaceholder
      imageUrl={destinationCard?.image_url}
      destination={destinationCard?.title}
      isLoading={isGenerating || day_cards.length === 0}
    />
  );

  return (
    <>
      {/* ========== DESKTOP LAYOUT ========== */}
      <div className="hidden lg:block h-full overflow-y-auto custom-scrollbar">
        {/* Flex layout: Timeline (60%) + Map (40%, 300px height, sticky) */}
        <div className="flex gap-6 p-4">
          {/* LEFT: Timeline content */}
          <div className="flex-1 min-w-0">
            <div id="itinerary-content" className="flex flex-col space-y-4">
              {timelineContent}
            </div>
          </div>

          {/* RIGHT: Map panel - sticky, 300px height */}
          <div className="w-[400px] shrink-0">
            <div className="sticky top-20">
              <div className="h-[300px] rounded-xl overflow-hidden border border-white/10 shadow-lg">
                {mapContent}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ========== MOBILE LAYOUT (Bottom Sheet Pattern) ========== */}
      <div className="lg:hidden relative h-full">
        {/* Map Background - visible behind sheet */}
        <div className="absolute inset-0 z-0">
          {mapContent}
        </div>

        {/* Bottom Sheet Container */}
        <div
          className={cn(
            'absolute bottom-0 left-0 right-0 z-10 flex flex-col',
            'bg-white dark:bg-zinc-900 rounded-t-3xl',
            'shadow-[0_-4px_20px_-5px_rgba(0,0,0,0.15)]',
            'transition-all duration-300 ease-out',
            isMobileExpanded ? 'h-[85vh]' : 'h-[50vh]'
          )}
        >
          {/* Drag Handle */}
          <button
            onClick={() => setIsMobileExpanded(!isMobileExpanded)}
            className="w-full py-3 flex flex-col items-center gap-1 border-b border-zinc-200 dark:border-zinc-800"
          >
            <div className="w-12 h-1.5 bg-zinc-300 dark:bg-zinc-700 rounded-full" />
            <div className="flex items-center gap-1 text-[10px] text-zinc-400">
              <ChevronUp
                className={cn(
                  'w-3 h-3 transition-transform duration-300',
                  isMobileExpanded && 'rotate-180'
                )}
              />
              {isMobileExpanded ? 'Collapse' : 'Expand'}
            </div>
          </button>

          {/* Scrollable Content */}
          <div className="flex-1 overflow-y-auto px-4 pb-[env(safe-area-inset-bottom)]">
            <div className="flex flex-col space-y-4 py-4">
              {timelineContent}
            </div>
          </div>
        </div>

        {/* Floating Map Action Button (bottom-right, above safe area) */}
        <button
          onClick={() => setIsMobileMapOpen(true)}
          className={cn(
            'fixed bottom-[calc(50vh+1rem)] right-4 z-20',
            'flex items-center gap-2 px-4 py-3 rounded-full shadow-lg',
            'bg-white dark:bg-zinc-800 border border-border',
            'hover:shadow-xl transition-shadow'
          )}
        >
          <Map className="w-5 h-5 text-emerald-600" />
          <span className="text-sm font-medium">View Route</span>
        </button>

        {/* Full-screen map sheet for mobile */}
        <Sheet open={isMobileMapOpen} onOpenChange={setIsMobileMapOpen}>
          <SheetContent side="bottom" className="h-[90vh] p-0">
            <div className="h-full flex flex-col">
              {/* Drag handle */}
              <div className="flex justify-center py-3 border-b">
                <div className="w-12 h-1.5 rounded-full bg-zinc-300 dark:bg-zinc-700" />
              </div>
              {/* Full-screen map */}
              <div className="flex-1">
                {mapContent}
              </div>
            </div>
          </SheetContent>
        </Sheet>
      </div>

      {/* ========== BOOKING DRAWER ========== */}
      <BookingDrawer
        category={bookingDrawerCategory}
        tiles={tiles}
        savedTileIds={savedTileIds}
        onSave={onSaveTile}
        onClose={handleCloseBookingDrawer}
      />
    </>
  );
}

export default S3ItineraryView;
