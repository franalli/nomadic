/**
 * S3ItineraryView
 *
 * Itinerary ready state - shows day cards and overview.
 * Day cards are collapsed by default, max 1 expanded at a time.
 */

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import {
  ChevronDown,
  ChevronRight,
  Moon,
  Plane,
  PlaneLanding,
  PlaneTakeoff,
  ShieldAlert,
  Sun,
  Sunset,
} from 'lucide-react';
import React from 'react';

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type {
  DayBlock,
  DayCard,
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
  /** Callback when a drop is rejected on a safety buffer (for toast) */
  onDropRejected?: (message: string) => void;
}

// =============================================================================
// Animation Variants (Tetris-style staggered loading)
// =============================================================================

/**
 * Get animation phase for a day card based on its type.
 * Phase 1: Bookends (arrival/departure) - appear first
 * Phase 2: Safety buffers - lock in with pulse
 * Phase 3: Activities - fill the gaps
 */
function getAnimationPhase(card: DayCard, isFirst: boolean, isLast: boolean): number {
  const isArrival = isFirst || card.blocks.some((b) => b.buffer_type === 'arrival');
  const isDeparture = isLast || card.blocks.some((b) => b.buffer_type === 'departure');
  const hasSafetyBuffer = card.blocks.some((b) =>
    ['no_fly', 'acclimatization', 'rest_day'].includes(b.buffer_type || '')
  );

  if (isArrival || isDeparture) return 1; // Bookends first
  if (hasSafetyBuffer) return 2; // Safety buffers second
  return 3; // Activities last
}

const cardVariants = {
  hidden: {
    opacity: 0,
    y: 20,
    scale: 0.95,
  },
  visible: (phase: number) => ({
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      duration: 0.4,
      delay: phase * 0.15, // Stagger by phase
      ease: [0.25, 0.46, 0.45, 0.94],
    },
  }),
  safetyPulse: {
    scale: [1, 1.02, 1],
    transition: {
      duration: 0.3,
      delay: 0.5,
    },
  },
};

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.08,
    },
  },
};

function PeriodIcon({ period }: { period: DayBlock['period'] }) {
  const iconClass = "w-3 h-3";
  switch (period) {
    case 'morning':
      return <Sun className={`${iconClass} text-amber-400`} />;
    case 'afternoon':
      return <Sunset className={`${iconClass} text-orange-400`} />;
    case 'evening':
      return <Moon className={`${iconClass} text-blue-400`} />;
    default:
      return null;
  }
}

/**
 * Determines if a buffer type is a safety constraint (vs logistics).
 * Safety buffers get hazard styling, logistics get neutral styling.
 */
function isSafetyBuffer(bufferType?: DayBlock['buffer_type']): boolean {
  return ['no_fly', 'acclimatization', 'rest_day'].includes(bufferType || '');
}

/**
 * BufferBlock Component
 *
 * Renders safety constraints and logistics blocks with distinct styling:
 * - Safety (No-Fly, Acclimatization): Amber with diagonal hatch pattern
 * - Logistics (Arrival, Departure): Blue/neutral styling
 */
function BufferBlock({ block }: { block: DayBlock }) {
  const isSafety = isSafetyBuffer(block.buffer_type);

  // Choose icon based on buffer type
  const getIcon = () => {
    switch (block.buffer_type) {
      case 'arrival':
        return <PlaneLanding className="w-4 h-4" />;
      case 'departure':
        return <PlaneTakeoff className="w-4 h-4" />;
      case 'no_fly':
      case 'acclimatization':
      case 'rest_day':
        return <ShieldAlert className="w-4 h-4" />;
      default:
        return <Plane className="w-4 h-4" />;
    }
  };

  // Get label based on buffer type
  const getLabel = () => {
    switch (block.buffer_type) {
      case 'no_fly':
        return 'SAFETY PROTOCOL: No-Fly Interval';
      case 'acclimatization':
        return 'SAFETY PROTOCOL: Acclimatization';
      case 'rest_day':
        return 'SAFETY PROTOCOL: Rest Day';
      case 'arrival':
        return 'Arrival Day';
      case 'departure':
        return 'Departure Day';
      default:
        return 'Logistics';
    }
  };

  const content = (
    <div
      className={cn(
        'relative rounded border-l-2 p-3 text-xs font-mono mb-2 overflow-hidden transition-all',
        isSafety
          ? 'bg-amber-950/10 border-amber-500/50 text-amber-500'
          : 'bg-blue-950/10 border-blue-500/30 text-blue-400'
      )}
    >
      {/* Hazard hatch pattern overlay for Safety blocks */}
      {isSafety && (
        <div
          className="absolute inset-0 opacity-[0.03] pointer-events-none"
          style={{
            backgroundImage:
              'linear-gradient(45deg, #000 25%, transparent 25%, transparent 50%, #000 50%, #000 75%, transparent 75%, transparent)',
            backgroundSize: '10px 10px',
          }}
        />
      )}

      <div className="flex items-center gap-2 relative z-10">
        {getIcon()}
        <span className="uppercase tracking-wider font-bold text-[10px]">
          {getLabel()}
        </span>
      </div>

      <div className="mt-1 pl-6 opacity-80 relative z-10 font-sans text-xs">
        {block.summary || block.buffer_reason}
      </div>
    </div>
  );

  // Wrap safety blocks with tooltip showing the specific rule
  if (isSafety && block.buffer_reason) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            {content}
          </TooltipTrigger>
          <TooltipContent side="right" className="max-w-xs">
            <p className="text-xs font-mono">{block.buffer_reason}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return content;
}

function DayCardComponent({
  card,
  isExpanded,
  onToggle,
  isFirst,
  isLast,
  onDropRejected,
}: {
  card: DayCard;
  isExpanded: boolean;
  onToggle: () => void;
  isFirst?: boolean;
  isLast?: boolean;
  /** Callback when a drop is rejected on a safety buffer */
  onDropRejected?: (message: string) => void;
}) {
  // Check if this is a buffer day (all blocks are buffers or it's arrival/departure)
  const isBufferDay = card.blocks.every((b) => b.is_buffer);

  // Determine day type for special styling
  const isArrivalDay = isFirst || card.blocks.some((b) => b.buffer_type === 'arrival');
  const isDepartureDay = isLast || card.blocks.some((b) => b.buffer_type === 'departure');
  const hasSafetyBuffer = card.blocks.some((b) => isSafetyBuffer(b.buffer_type));

  // Drag rejection state for visual feedback
  const [isDragRejecting, setIsDragRejecting] = React.useState(false);

  // Get icon for bookend days
  const getDayIcon = () => {
    if (isArrivalDay) return <PlaneLanding className="w-3 h-3 text-blue-400" />;
    if (isDepartureDay) return <PlaneTakeoff className="w-3 h-3 text-blue-400" />;
    if (hasSafetyBuffer) return <ShieldAlert className="w-3 h-3 text-amber-400" />;
    return null;
  };

  // Drag prevention for safety buffer days
  const handleDragOver = React.useCallback(
    (e: React.DragEvent) => {
      if (hasSafetyBuffer) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'none';
        setIsDragRejecting(true);
      }
    },
    [hasSafetyBuffer]
  );

  const handleDragLeave = React.useCallback(() => {
    setIsDragRejecting(false);
  }, []);

  const handleDrop = React.useCallback(
    (e: React.DragEvent) => {
      if (hasSafetyBuffer) {
        e.preventDefault();
        e.stopPropagation();
        setIsDragRejecting(false);

        // Get buffer type for specific message
        const bufferBlock = card.blocks.find((b) => isSafetyBuffer(b.buffer_type));
        const bufferType = bufferBlock?.buffer_type;

        let message = 'Cannot schedule activity during safety buffer';
        if (bufferType === 'no_fly') {
          message = 'Cannot schedule activity during No-Fly Interval';
        } else if (bufferType === 'acclimatization') {
          message = 'Cannot schedule activity during Acclimatization Day';
        } else if (bufferType === 'rest_day') {
          message = 'Cannot schedule activity during Rest Day';
        }

        onDropRejected?.(message);

        // Brief red pulse animation
        setTimeout(() => setIsDragRejecting(false), 300);
      }
    },
    [hasSafetyBuffer, card.blocks, onDropRejected]
  );

  return (
    <div
      className={cn(
        'rounded-lg border overflow-hidden transition-all',
        isBufferDay && hasSafetyBuffer
          ? 'bg-amber-950/5 border-amber-500/20 border-dashed'
          : isBufferDay
            ? 'bg-blue-950/5 border-blue-500/20 border-dashed'
            : 'bg-zinc-800/40 border-zinc-700/50',
        // Drag rejection visual feedback
        isDragRejecting && 'ring-2 ring-red-500/50 border-red-500/50 animate-pulse'
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-zinc-700/20 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span
            className={cn(
              'text-xs font-medium px-2 py-0.5 rounded flex items-center gap-1.5',
              hasSafetyBuffer
                ? 'text-amber-400 bg-amber-500/10'
                : isBufferDay
                  ? 'text-blue-400 bg-blue-500/10'
                  : 'text-zinc-500 bg-zinc-700/50'
            )}
          >
            {getDayIcon()}
            Day {card.day_number}
          </span>
          <span className="text-sm text-zinc-200">{card.label}</span>
        </div>
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-zinc-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-zinc-400" />
        )}
      </button>

      {isExpanded && card.blocks.length > 0 && (
        <div className="px-4 pb-3 pt-1 border-t border-zinc-700/30 space-y-2">
          {card.blocks.slice(0, 3).map((block, idx) => {
            // Render BufferBlock for buffer blocks
            if (block.is_buffer) {
              return <BufferBlock key={idx} block={block} />;
            }

            // Regular activity block
            return (
              <div key={idx} className="flex items-start gap-2 py-1">
                <PeriodIcon period={block.period} />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-zinc-300 capitalize">
                      {block.period}
                    </span>
                    {block.intensity && (
                      <span
                        className={`text-xs px-1.5 py-0.5 rounded ${
                          block.intensity === 'light'
                            ? 'bg-green-900/30 text-green-400'
                            : block.intensity === 'moderate'
                              ? 'bg-amber-900/30 text-amber-400'
                              : 'bg-red-900/30 text-red-400'
                        }`}
                      >
                        {block.intensity}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-zinc-400 mt-0.5">{block.summary}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
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
  destinationCard: _destinationCard,
  animateEntrance = true,
  onDropRejected,
}: S3ItineraryViewProps) {
  // destinationCard reserved for future use (header owns destination display)
  void _destinationCard;

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

  const handleToggleDay = (dayNumber: number) => {
    setExpandedDay((prev) => (prev === dayNumber ? null : dayNumber));
  };

  return (
    <div id="itinerary-content" className="flex flex-col p-4 space-y-4">
      {/* Overview */}
      {itinerary_overview && <OverviewCard overview={itinerary_overview} />}

      {/* Day cards - Tetris-style staggered animation */}
      <motion.div
        className="space-y-2"
        variants={shouldAnimate ? containerVariants : undefined}
        initial={shouldAnimate ? 'hidden' : false}
        animate={shouldAnimate ? 'visible' : false}
      >
        <AnimatePresence mode="popLayout">
          {day_cards.map((card, idx) => {
            const isFirst = idx === 0;
            const isLast = idx === day_cards.length - 1;
            const phase = getAnimationPhase(card, isFirst, isLast);
            const hasSafetyBuffer = card.blocks.some((b) =>
              ['no_fly', 'acclimatization', 'rest_day'].includes(b.buffer_type || '')
            );

            return (
              <motion.div
                key={card.day_number}
                custom={phase}
                variants={shouldAnimate ? cardVariants : undefined}
                initial={shouldAnimate ? 'hidden' : false}
                animate={
                  shouldAnimate
                    ? hasSafetyBuffer
                      ? ['visible', 'safetyPulse']
                      : 'visible'
                    : false
                }
                layout
              >
                <DayCardComponent
                  card={card}
                  isExpanded={expandedDay === card.day_number}
                  onToggle={() => handleToggleDay(card.day_number)}
                  isFirst={isFirst}
                  isLast={isLast}
                  onDropRejected={onDropRejected}
                />
              </motion.div>
            );
          })}
        </AnimatePresence>
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
  );
}

export default S3ItineraryView;
