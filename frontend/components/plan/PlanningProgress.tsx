/**
 * PlanningProgress
 *
 * Visual progress indicator for the PLANNING mode.
 * Shows completion status of required trip inputs and overall progress.
 *
 * @see docs/ux_unified_architecture.md for the two-mode system specification
 */

'use client';

import { Calendar, Check, Circle, MapPin, Plane } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { PlanningPhase } from '@/types/plan-envelope';

interface PlanningProgressProps {
  phase: PlanningPhase;
  progress: number;
  className?: string;
  /** Compact mode - shows only progress bar */
  compact?: boolean;
}

interface ProgressItemProps {
  label: string;
  value?: string;
  isComplete: boolean;
  isRequired?: boolean;
  icon: React.ReactNode;
}

function ProgressItem({ label, value, isComplete, isRequired = false, icon }: ProgressItemProps) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <div
        className={cn(
          'flex h-5 w-5 items-center justify-center rounded-full',
          isComplete
            ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400'
            : 'bg-zinc-200 text-zinc-500 dark:bg-zinc-700/50 dark:text-zinc-500'
        )}
      >
        {isComplete ? <Check className="h-3 w-3" /> : icon}
      </div>
      <span
        className={cn(
          'transition-colors',
          isComplete
            ? 'text-zinc-700 dark:text-zinc-300'
            : 'text-zinc-500 dark:text-zinc-500'
        )}
      >
        {isComplete && value ? (
          <>
            <span className="text-zinc-500">{label}:</span>{' '}
            <span className="font-medium text-zinc-900 dark:text-zinc-200">{value}</span>
          </>
        ) : (
          <>
            {label}
            {isRequired && !isComplete && (
              <span className="ml-1 text-xs text-amber-600 dark:text-amber-500">(required)</span>
            )}
          </>
        )}
      </span>
    </div>
  );
}

export function PlanningProgress({
  phase,
  progress,
  className,
  compact = false,
}: PlanningProgressProps) {
  if (compact) {
    // Compact mode: just the progress bar
    return (
      <div className={cn('flex items-center gap-3', className)}>
        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-zinc-300/50 dark:bg-zinc-700/50">
          <div
            className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-zinc-600 dark:text-zinc-500">{progress}%</span>
      </div>
    );
  }

  // Full mode: progress bar + checklist
  return (
    <div className={cn('space-y-3', className)}>
      {/* Progress bar with percentage */}
      <div className="flex items-center gap-3">
        <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Trip Progress</div>
        <div className="flex-1 h-1.5 overflow-hidden rounded-full bg-zinc-300/50 dark:bg-zinc-700/50">
          <div
            className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-zinc-600 dark:text-zinc-500">{progress}%</span>
      </div>

      {/* Checklist items */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        <ProgressItem
          label="Destination"
          isComplete={phase.hasDestination}
          isRequired
          icon={<MapPin className="h-3 w-3" />}
        />
        <ProgressItem
          label="Origin"
          isComplete={phase.hasOrigin}
          icon={<Plane className="h-3 w-3" />}
        />
        <ProgressItem
          label="Dates"
          isComplete={phase.hasDates}
          isRequired
          icon={<Calendar className="h-3 w-3" />}
        />
        <ProgressItem
          label="Itinerary"
          isComplete={phase.hasItinerary}
          icon={<Circle className="h-3 w-3" />}
        />
      </div>

      {/* Hint message when dates are missing */}
      {!phase.hasDates && phase.hasDestination && (
        <div className="text-xs text-zinc-500 dark:text-zinc-500 italic">
          Add dates to see your day-by-day itinerary
        </div>
      )}
    </div>
  );
}

/**
 * Inline progress indicator for header use.
 * Shows mode pill + compact progress.
 */
interface ModeIndicatorProps {
  mode: 'planning' | 'booking';
  phase: PlanningPhase;
  progress: number;
  onModeClick?: (mode: 'planning' | 'booking') => void;
  canViewBooking?: boolean;
  className?: string;
}

export function ModeIndicator({
  mode,
  phase,
  progress,
  onModeClick,
  canViewBooking = false,
  className,
}: ModeIndicatorProps) {
  return (
    <div className={cn('flex items-center gap-3', className)}>
      {/* Mode pills - following design-system.md Section 14 (Primary Navigation) */}
      <div className="flex items-center gap-1 p-1 bg-zinc-100 dark:bg-black/40 rounded-full border border-zinc-200 dark:border-white/10 backdrop-blur-xl">
        <button
          onClick={() => onModeClick?.('planning')}
          className={cn(
            'px-4 py-2 rounded-full text-xs font-bold uppercase tracking-widest transition-all duration-150',
            mode === 'planning'
              // Active: "The Beacon" - Solid White (Light) / Solid White with glow (Dark)
              ? [
                  'bg-white text-zinc-950 ring-1 ring-black/5 shadow-md',
                  'dark:bg-white dark:text-zinc-950 dark:ring-0',
                  'dark:shadow-[0_0_15px_-3px_rgba(255,255,255,0.4)]',
                ]
              // Inactive
              : [
                  'text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100/80',
                  'dark:text-white/60 dark:hover:text-white dark:hover:bg-white/10',
                ]
          )}
        >
          PLANNING
        </button>
        <button
          onClick={() => canViewBooking && onModeClick?.('booking')}
          disabled={!canViewBooking}
          className={cn(
            'px-4 py-2 rounded-full text-xs font-bold uppercase tracking-widest transition-all duration-150',
            mode === 'booking'
              // Active: "The Beacon" - Solid White
              ? [
                  'bg-white text-zinc-950 ring-1 ring-black/5 shadow-md',
                  'dark:bg-white dark:text-zinc-950 dark:ring-0',
                  'dark:shadow-[0_0_15px_-3px_rgba(255,255,255,0.4)]',
                ]
              : canViewBooking
                // Inactive (unlocked)
                ? [
                    'text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100/80',
                    'dark:text-white/60 dark:hover:text-white dark:hover:bg-white/10',
                  ]
                // Locked state
                : [
                    'text-zinc-400 opacity-40 cursor-not-allowed',
                    'dark:text-white/40 dark:opacity-40',
                  ]
          )}
        >
          BOOKING
        </button>
      </div>

      {/* Progress (PLANNING mode only) */}
      {mode === 'planning' && (
        <PlanningProgress phase={phase} progress={progress} compact />
      )}
    </div>
  );
}
