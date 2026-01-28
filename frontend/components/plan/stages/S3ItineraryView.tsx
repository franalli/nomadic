/**
 * S3ItineraryView
 *
 * Itinerary ready state - shows day cards and overview.
 * Day cards are collapsed by default, max 1 expanded at a time.
 */

'use client';

import { motion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import React from 'react';

import { Button } from '@/components/ui/button';
import { DestinationMapPlaceholder } from '@/components/plan/DestinationMapPlaceholder';
import { TimelineThread } from '@/components/plan/TimelineThread';
import { TimelineSkeleton } from '@/components/plan/timeline/TimelineSkeleton';
import { InteractiveMap, type MapItem } from '@/components/map/InteractiveMap';
import { useScrollSpy } from '@/hooks/useScrollSpy';
import type {
  DestinationCard,
  ItineraryOverview,
  PlanViewModel,
} from '@/types/plan-envelope';

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
}: S3ItineraryViewProps) {
  const { day_cards = [], itinerary_overview, itinerary_assumptions } = viewModel;
  const [expandedDay, setExpandedDay] = React.useState<number | null>(null);

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

  // Prepare map items from day cards (blocks with coordinates)
  const mapItems = React.useMemo((): MapItem[] => {
    const items: MapItem[] = [];
    day_cards.forEach((card) => {
      card.blocks.forEach((block, blockIndex) => {
        if (block.coordinates) {
          const blockId = block.id || `block-${card.day_number}-${blockIndex}`;
          items.push({
            id: blockId,
            title: block.activity_type || block.summary || `Day ${card.day_number}`,
            type: block.activity_type || 'activity',
            coordinates: block.coordinates,
          });
        }
      });
    });
    return items;
  }, [day_cards]);

  // Scroll spy for map synchronization
  const itemIds = React.useMemo(() => mapItems.map((i) => i.id), [mapItems]);
  const activeBlockId = useScrollSpy(itemIds);

  // Check if we have map-ready items (with coordinates)
  const hasMapItems = mapItems.length > 0;

  return (
    <div className="h-full flex flex-col">
      {/* Split-screen layout: Timeline (7 cols) + Map placeholder (5 cols) */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-0 lg:gap-6 min-h-0">
        {/* LEFT: Scrollable itinerary content */}
        <div className="lg:col-span-7 overflow-y-auto custom-scrollbar">
          <div id="itinerary-content" className="flex flex-col p-4 space-y-4">
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
          </div>
        </div>

        {/* RIGHT: Map (desktop only) - sticky for scroll sync */}
        <div className="hidden lg:block lg:col-span-5 relative">
          <div className="sticky top-4 h-[calc(100vh-8rem)] rounded-xl overflow-hidden">
            {hasMapItems ? (
              <InteractiveMap
                items={mapItems}
                activeItemId={activeBlockId}
                defaultCenter={{ lat: 25.2048, lng: 55.2708, zoom: 10 }} // Dubai default
              />
            ) : (
              <DestinationMapPlaceholder
                imageUrl={destinationCard?.image_url}
                destination={destinationCard?.title}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default S3ItineraryView;
