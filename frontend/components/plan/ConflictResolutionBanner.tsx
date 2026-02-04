/**
 * ConflictResolutionBanner
 *
 * Shows when ItineraryBuilder detects constraint conflicts.
 * Presents resolution options as clickable chips.
 *
 * Triggers when: ItineraryBuilder.success === false && conflicts.length > 0
 *
 * Resolution Actions:
 * - extend_dates: Updates trip dates, auto-retriggers generation
 * - remove_specialist: Removes specialist from queue, retriggers
 * - show_partial: Shows what ItineraryBuilder could schedule
 *
 * @see docs/ux_unified_architecture.md - Path A: Conflict Resolution UX
 */

'use client';

import { motion } from 'framer-motion';
import { AlertTriangle, Calendar, Minus } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface ConflictData {
  /** Conflict type from backend */
  type: 'constraint_clash' | 'temporal_conflict' | 'capacity_exceeded';
  /** Human-readable message */
  message: string;
  /** Specialists involved in the conflict */
  specialists: string[];
  /** Suggested resolution options */
  resolutions?: ConflictResolution[];
}

export interface ConflictResolution {
  /** Action type - maps to backend Resolution.action */
  action: 'extend_dates' | 'extend_trip' | 'remove_specialist' | 'reduce_activities';
  /** Display label (from backend: description) */
  label: string;
  /** Backend: description field (alternative to label) */
  description?: string;
  /** Backend: suggested new trip duration in days */
  new_duration?: number;
  /** Backend: which specialist to keep (remove the others) */
  keep_specialist?: string;
  /** Backend: how feasible this resolution is */
  feasibility?: 'recommended' | 'possible' | 'not_recommended';
}

interface ConflictResolutionBannerProps {
  /** Conflict details from ItineraryBuilder */
  conflict: ConflictData;
  /** Current trip duration in days */
  currentDays?: number;
  /** Suggested minimum days to resolve conflict */
  suggestedDays?: number;
  /** Callback when user selects a resolution */
  onResolve: (resolution: ConflictResolution) => void;
  /** Callback to dismiss the banner */
  onDismiss?: () => void;
  className?: string;
}

// Partial timeline auto-renders when conflicts exist + day_cards present
// No show_partial option needed - user sees unschedulable blocks inline
const DEFAULT_RESOLUTIONS: ConflictResolution[] = [
  {
    action: 'extend_dates',
    label: 'Extend trip',
  },
  {
    action: 'remove_specialist',
    label: 'Focus on one',
  },
];

export function ConflictResolutionBanner({
  conflict,
  currentDays,
  suggestedDays,
  onResolve,
  onDismiss,
  className,
}: ConflictResolutionBannerProps) {
  // Use provided resolutions or defaults, filtering out dead buttons
  // (remove_specialist endpoint doesn't exist yet)
  const resolutions = (conflict.resolutions ?? DEFAULT_RESOLUTIONS).filter(
    (r) => r.action !== 'remove_specialist' && r.action !== 'reduce_activities'
  );

  // Build resolution labels with context
  const getResolutionLabel = (resolution: ConflictResolution): string => {
    // Use backend's new_duration if available, else fall back to suggestedDays prop
    if (resolution.action === 'extend_dates') {
      const days = resolution.new_duration ?? suggestedDays;
      if (days) return `Extend to ${days} days`;
    }
    // Use backend's keep_specialist if available
    if (resolution.action === 'remove_specialist') {
      if (resolution.keep_specialist) {
        return `Focus on ${resolution.keep_specialist}`;
      }
      if (conflict.specialists.length > 1) {
        return `Focus on ${conflict.specialists[0]}`;
      }
    }
    // Use description from backend if label is not set
    return resolution.label || resolution.description || 'Resolve';
  };

  // Get icon for resolution action
  const getResolutionIcon = (action: ConflictResolution['action']) => {
    switch (action) {
      case 'extend_dates':
      case 'extend_trip':
        return <Calendar className="w-3.5 h-3.5" />;
      case 'remove_specialist':
      case 'reduce_activities':
        return <Minus className="w-3.5 h-3.5" />;
      default:
        return <Minus className="w-3.5 h-3.5" />;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className={cn(
        'w-full p-4 rounded-xl',
        'bg-amber-950/30 backdrop-blur-sm',
        'border border-amber-500/30',
        className
      )}
    >
      {/* Header with warning icon */}
      <div className="flex items-start gap-3">
        <div className="p-1.5 rounded-lg bg-amber-500/20 shrink-0">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
        </div>

        <div className="flex-1 min-w-0">
          {/* Conflict message */}
          <p className="text-sm font-medium text-amber-200">
            {conflict.message}
          </p>

          {/* Context about current trip */}
          {currentDays && suggestedDays && (
            <p className="text-xs text-amber-400/70 mt-1">
              {currentDays} days available, need {suggestedDays} days minimum
            </p>
          )}

          {/* Specialists involved */}
          {conflict.specialists.length > 0 && (
            <div className="flex items-center gap-1 mt-2">
              <span className="text-xs text-zinc-500">Involved:</span>
              {conflict.specialists.map((specialist) => (
                <span
                  key={specialist}
                  className="px-2 py-0.5 text-xs font-medium rounded-full bg-zinc-800 text-zinc-300"
                >
                  {specialist}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Dismiss button */}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
            aria-label="Dismiss"
          >
            <span className="text-lg leading-none">&times;</span>
          </button>
        )}
      </div>

      {/* Resolution options */}
      <div className="mt-4">
        <p className="text-xs text-zinc-500 mb-2">Choose resolution:</p>
        <div className="flex flex-wrap gap-2">
          {resolutions.map((resolution, index) => {
            // Create unique key: action + specialist (for reduce_activities) or index
            const uniqueKey = resolution.keep_specialist
              ? `${resolution.action}-${resolution.keep_specialist}`
              : `${resolution.action}-${index}`;

            // Check if this is an "extend" type action
            const isExtendAction = resolution.action === 'extend_dates' || resolution.action === 'extend_trip';
            // Check if this is a "reduce/remove" type action
            const isReduceAction = resolution.action === 'remove_specialist' || resolution.action === 'reduce_activities';

            return (
            <motion.button
              key={uniqueKey}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => onResolve(resolution)}
              className={cn(
                'flex items-center gap-2',
                'px-3 py-2 rounded-lg',
                'text-xs font-medium',
                'transition-colors',
                // Different styling per action type
                isExtendAction
                  ? 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30'
                  : isReduceAction
                    ? 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700'
                    : 'bg-zinc-800/50 text-zinc-400 hover:bg-zinc-700/50 border border-zinc-700/50'
              )}
            >
              {getResolutionIcon(resolution.action)}
              <span>{getResolutionLabel(resolution)}</span>
            </motion.button>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}

export default ConflictResolutionBanner;
