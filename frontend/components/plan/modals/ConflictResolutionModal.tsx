/**
 * ConflictResolutionModal
 *
 * Modal for handling multi-specialist constraint conflicts.
 * Shows conflict details and actionable resolution options.
 *
 * @see docs/ux_unified_architecture.md Multi-Specialist Orchestration
 */

'use client';

import {
  AlertTriangle,
  Calendar,
  Check,
  Focus,
  X,
} from 'lucide-react';

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

export interface Conflict {
  type: 'temporal_capacity' | 'constraint_clash' | 'insufficient_days';
  severity: 'blocking' | 'strong' | 'soft';
  day?: number;
  specialists: string[];
  message: string;
  overflow_hours?: number;
}

export interface Resolution {
  action: 'extend_trip' | 'reduce_activities' | 'reorder' | 'shift_activities';
  description: string;
  new_duration?: number;
  keep_specialist?: string;
  feasibility: 'recommended' | 'possible' | 'not_recommended';
}

interface ConflictResolutionModalProps {
  /** Whether modal is open */
  open: boolean;
  /** Close handler */
  onOpenChange: (open: boolean) => void;
  /** List of detected conflicts */
  conflicts: Conflict[];
  /** Available resolution options */
  resolutions: Resolution[];
  /** Current trip duration in days */
  currentDuration: number;
  /** Callback when user selects extend trip */
  onExtendTrip?: (newDuration: number) => void;
  /** Callback when user chooses to focus on one specialist */
  onKeepSpecialist?: (specialist: string) => void;
  /** Callback to dismiss and try anyway */
  onDismiss?: () => void;
}

// =============================================================================
// Helpers
// =============================================================================

function getConflictIcon(type: Conflict['type']) {
  switch (type) {
    case 'insufficient_days':
      return Calendar;
    case 'temporal_capacity':
      return AlertTriangle;
    default:
      return AlertTriangle;
  }
}

function getResolutionIcon(action: Resolution['action']) {
  switch (action) {
    case 'extend_trip':
      return Calendar;
    case 'reduce_activities':
      return Focus;
    default:
      return Check;
  }
}

function formatSpecialist(specialist: string): string {
  return specialist.charAt(0).toUpperCase() + specialist.slice(1).replace(/_/g, ' ');
}

// =============================================================================
// Component
// =============================================================================

export function ConflictResolutionModal({
  open,
  onOpenChange,
  conflicts,
  resolutions,
  currentDuration,
  onExtendTrip,
  onKeepSpecialist,
  onDismiss,
}: ConflictResolutionModalProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg p-0 overflow-y-auto">
        <SheetHeader className="p-6 border-b bg-amber-50 dark:bg-amber-950/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-900/50 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <SheetTitle className="text-lg">Constraint Conflict Detected</SheetTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Your trip needs adjustment to fit all activities
              </p>
            </div>
          </div>
        </SheetHeader>

        <div className="p-6 space-y-6">
          {/* Conflict Details */}
          <section>
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              The Problem
            </h3>
            <div className="space-y-3">
              {conflicts.map((conflict, idx) => {
                const Icon = getConflictIcon(conflict.type);
                return (
                  <div
                    key={idx}
                    className="flex gap-3 p-4 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900/50"
                  >
                    <Icon className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm font-medium text-red-800 dark:text-red-200">
                        {conflict.message}
                      </p>
                      {conflict.specialists.length > 0 && (
                        <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                          Specialists involved: {conflict.specialists.map(formatSpecialist).join(', ')}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Resolution Options */}
          <section>
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Recommended Solutions
            </h3>
            <div className="space-y-3">
              {resolutions.map((resolution, idx) => {
                const Icon = getResolutionIcon(resolution.action);
                const isRecommended = resolution.feasibility === 'recommended';

                return (
                  <button
                    key={idx}
                    onClick={() => {
                      if (resolution.action === 'extend_trip' && resolution.new_duration && onExtendTrip) {
                        onExtendTrip(resolution.new_duration);
                        onOpenChange(false);
                      } else if (resolution.action === 'reduce_activities' && resolution.keep_specialist && onKeepSpecialist) {
                        onKeepSpecialist(resolution.keep_specialist);
                        onOpenChange(false);
                      }
                    }}
                    className={cn(
                      'w-full text-left p-4 rounded-lg border transition-all hover:shadow-md',
                      isRecommended
                        ? 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800 hover:border-emerald-400'
                        : 'bg-white dark:bg-zinc-800/50 border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <div
                        className={cn(
                          'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
                          isRecommended
                            ? 'bg-emerald-100 dark:bg-emerald-900/50'
                            : 'bg-zinc-100 dark:bg-zinc-700'
                        )}
                      >
                        {isRecommended ? (
                          <Check className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                        ) : (
                          <Icon className="w-4 h-4 text-zinc-500" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={cn(
                            'font-semibold text-sm',
                            isRecommended ? 'text-emerald-800 dark:text-emerald-200' : ''
                          )}>
                            {resolution.description}
                          </span>
                          {isRecommended && (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-200 dark:bg-emerald-800 text-emerald-800 dark:text-emerald-200">
                              Recommended
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          {resolution.action === 'extend_trip' && resolution.new_duration
                            ? `Extend your trip from ${currentDuration} to ${resolution.new_duration} days`
                            : resolution.action === 'reduce_activities' && resolution.keep_specialist
                            ? `Focus on ${formatSpecialist(resolution.keep_specialist)} activities only`
                            : 'Adjust your itinerary to resolve the conflict'}
                        </p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Dismiss Option */}
          {onDismiss && (
            <div className="pt-4 border-t">
              <button
                onClick={() => {
                  onDismiss();
                  onOpenChange(false);
                }}
                className="w-full py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Dismiss and try anyway
              </button>
            </div>
          )}
        </div>

        <button
          onClick={() => onOpenChange(false)}
          className="absolute top-4 right-4 p-2 rounded-lg hover:bg-muted transition-colors"
          aria-label="Close"
        >
          <X className="w-5 h-5" />
        </button>
      </SheetContent>
    </Sheet>
  );
}
