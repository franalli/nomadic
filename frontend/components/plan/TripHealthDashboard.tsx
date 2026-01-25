/**
 * TripHealthDashboard
 *
 * Replaces the General Agent card with an at-a-glance health status.
 * Shows constraint validation (green/yellow/red), inventory counts,
 * and critical alerts from blocking open_decisions.
 */

'use client';

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDot,
  Hotel,
  MapPin,
  Plane,
  XCircle,
} from 'lucide-react';
import React from 'react';

import { Button } from '@/components/ui/button';

import { cn } from '@/lib/utils';
import type { OpenDecision, ReadinessItem, TripHealth } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

// =============================================================================
// Types
// =============================================================================

/** Constraint violation from backend */
export interface ConstraintViolation {
  code: string;
  message: string;
  severity: 'blocking' | 'warning' | 'info';
  category: string;
  suggested_action?: string;
  suggested_specialist?: string;
}

// =============================================================================
// Props
// =============================================================================

interface TripHealthDashboardProps {
  /** Readiness items from backend */
  readiness: ReadinessItem[];
  /** All tiles for inventory counts */
  tiles: Record<string, Tile>;
  /** Open decisions for alerts (blocking ones become alerts) */
  openDecisions?: OpenDecision[];
  /** Constraint violations from backend (seasonal, budget, etc.) */
  constraintViolations?: ConstraintViolation[];
  /** Callback when user clicks to switch specialist */
  onSwitchSpecialist?: (specialist: string) => void;
  /** Optional className for styling */
  className?: string;
}

// =============================================================================
// Helpers
// =============================================================================

/**
 * Compute health data from readiness, tiles, and open_decisions.
 */
function computeTripHealth(
  readiness: ReadinessItem[],
  tiles: Record<string, Tile>,
  openDecisions?: OpenDecision[]
): TripHealth {
  // Map readiness items to constraint status
  const constraints = readiness.map((item) => ({
    key: item.key,
    status: item.ok ? ('valid' as const) : ('warning' as const),
    label: getConstraintLabel(item.key),
  }));

  // Count tiles by type
  const tileArray = Object.values(tiles);
  const inventory = {
    hotels: tileArray.filter((t) => t.type === 'hotel' || t.type === 'stay').length,
    flights: tileArray.filter((t) => t.type === 'flight').length,
    activities: tileArray.filter(
      (t) => t.type === 'activity' || t.type === 'experience' || t.type === 'tour'
    ).length,
  };

  // Extract blocking decisions as alerts
  const alerts: TripHealth['alerts'] = (openDecisions || [])
    .filter((d) => d.is_blocking)
    .map((d) => ({
      level: 'error' as const,
      message: d.statement,
    }));

  return { constraints, inventory, alerts };
}

/**
 * Get human-readable label for constraint key.
 */
function getConstraintLabel(key: string): string {
  const labels: Record<string, string> = {
    origin: 'Origin',
    destination: 'Destination',
    start_date: 'Start Date',
    end_date: 'End Date',
    travelers: 'Travelers',
    budget: 'Budget',
  };
  return labels[key] || key;
}

// =============================================================================
// Sub-components
// =============================================================================

/** Constraint status row */
function ConstraintRow({
  label,
  status,
}: {
  label: string;
  status: 'valid' | 'warning' | 'error';
}) {
  const statusConfig = {
    valid: {
      icon: CheckCircle2,
      color: 'text-emerald-500',
      bg: 'bg-emerald-500/10',
    },
    warning: {
      icon: CircleDot,
      color: 'text-amber-500',
      bg: 'bg-amber-500/10',
    },
    error: {
      icon: XCircle,
      color: 'text-red-500',
      bg: 'bg-red-500/10',
    },
  };

  const config = statusConfig[status];
  const Icon = config.icon;

  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className={cn('flex items-center gap-1', config.color)}>
        <Icon className="h-3.5 w-3.5" />
      </div>
    </div>
  );
}

/** Inventory count badge */
function InventoryBadge({
  icon: Icon,
  count,
  label,
}: {
  icon: React.ElementType;
  count: number;
  label: string;
}) {
  return (
    <div className="flex flex-col items-center gap-1 px-3 py-2 rounded-lg bg-muted/50">
      <Icon className="h-4 w-4 text-muted-foreground" />
      <span className="text-lg font-semibold text-card-foreground">{count}</span>
      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
        {label}
      </span>
    </div>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export function TripHealthDashboard({
  readiness,
  tiles,
  openDecisions,
  constraintViolations = [],
  onSwitchSpecialist,
  className,
}: TripHealthDashboardProps) {
  const health = React.useMemo(
    () => computeTripHealth(readiness, tiles, openDecisions),
    [readiness, tiles, openDecisions]
  );

  // Track previous violation count for animation
  const [prevViolationCount, setPrevViolationCount] = React.useState(constraintViolations.length);
  const [shouldPulse, setShouldPulse] = React.useState(false);

  // Trigger pulse animation when violations change
  React.useEffect(() => {
    if (constraintViolations.length > prevViolationCount) {
      setShouldPulse(true);
      const timer = setTimeout(() => setShouldPulse(false), 1000);
      return () => clearTimeout(timer);
    }
    setPrevViolationCount(constraintViolations.length);
  }, [constraintViolations.length, prevViolationCount]);

  // Only show constraints that have warnings/errors (valid ones are implicit)
  const problemConstraints = health.constraints.filter((c) => c.status !== 'valid');

  // Separate seasonal/actionable violations from others
  const seasonalViolations = constraintViolations.filter(
    (v) => v.category === 'seasonal' && v.suggested_specialist
  );
  const otherViolations = constraintViolations.filter(
    (v) => v.category !== 'seasonal' || !v.suggested_specialist
  );

  // Combine alerts from open decisions and non-actionable violations
  const allAlerts = [
    ...health.alerts,
    ...otherViolations.map((v) => ({
      level: v.severity === 'blocking' ? ('error' as const) : ('warning' as const),
      message: v.message,
    })),
  ];

  const hasViolations = constraintViolations.length > 0;
  const allValid = problemConstraints.length === 0 && !hasViolations;

  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-card overflow-hidden transition-all',
        shouldPulse && 'animate-pulse ring-2 ring-amber-500/50',
        hasViolations && 'border-amber-500/30',
        className
      )}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-border/50 bg-muted/30">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              'h-2 w-2 rounded-full transition-colors',
              allValid
                ? 'bg-emerald-500'
                : hasViolations
                  ? 'bg-amber-500'
                  : 'bg-amber-500'
            )}
          />
          <h4 className="text-sm font-medium text-card-foreground">Trip Health</h4>
          {allValid && (
            <span className="ml-auto text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">
              All set
            </span>
          )}
          {hasViolations && (
            <span className="ml-auto text-[10px] text-amber-600 dark:text-amber-400 font-medium">
              Needs review
            </span>
          )}
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Seasonal Violations with Action Buttons */}
        {seasonalViolations.length > 0 && (
          <div>
            <h5 className="text-[10px] uppercase tracking-wider text-amber-500 font-semibold mb-2">
              Seasonal Conflict
            </h5>
            <div className="space-y-2">
              {seasonalViolations.map((violation, idx) => (
                <div
                  key={idx}
                  className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 space-y-2"
                >
                  <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400">
                    <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                    <span>{violation.message}</span>
                  </div>
                  {violation.suggested_specialist && onSwitchSpecialist && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full text-xs h-7 border-amber-500/30 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10"
                      onClick={() => onSwitchSpecialist(violation.suggested_specialist!)}
                    >
                      <span>Try {violation.suggested_specialist} instead</span>
                      <ArrowRight className="h-3 w-3 ml-1" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Constraint Status (only show if issues exist) */}
        {problemConstraints.length > 0 && (
          <div>
            <h5 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
              Needs Attention
            </h5>
            <div className="space-y-0.5">
              {problemConstraints.map((c) => (
                <ConstraintRow key={c.key} label={c.label} status={c.status} />
              ))}
            </div>
          </div>
        )}

        {/* Inventory Summary */}
        <div>
          <h5 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
            Found Options
          </h5>
          <div className="grid grid-cols-3 gap-2">
            <InventoryBadge icon={Hotel} count={health.inventory.hotels} label="Hotels" />
            <InventoryBadge icon={Plane} count={health.inventory.flights} label="Flights" />
            <InventoryBadge icon={MapPin} count={health.inventory.activities} label="Activities" />
          </div>
        </div>

        {/* Critical Alerts */}
        {allAlerts.length > 0 && (
          <div>
            <h5 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
              Alerts
            </h5>
            <div className="space-y-2">
              {allAlerts.map((alert, idx) => (
                <div
                  key={idx}
                  className={cn(
                    'flex items-start gap-2 p-2 rounded text-xs',
                    alert.level === 'error'
                      ? 'bg-red-500/10 text-red-700 dark:text-red-400 border border-red-500/20'
                      : 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20'
                  )}
                >
                  <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                  <span>{alert.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default TripHealthDashboard;
