'use client';

import { Car, Hotel, Mountain, Plane } from 'lucide-react';
import { memo } from 'react';

import { deriveEffectivePhase } from '@/lib/plan-status';
import type { PlanStatus, SpecialistKey } from '@/types/plan-status';

interface SpecialistProgressProps {
  status: PlanStatus;
}

const SPECIALIST_ICONS: Record<SpecialistKey, typeof Plane> = {
  flights: Plane,
  hotels: Hotel,
  activities: Mountain,
  transport: Car,
};

const SPECIALIST_LABELS: Record<SpecialistKey, string> = {
  flights: 'Flights',
  hotels: 'Hotels',
  activities: 'Activities',
  transport: 'Transport',
};

/**
 * SpecialistProgress - System strip above chat input showing specialist updates.
 *
 * Subordinate to PlanHeaderStatus. Only shows when:
 * - Header is NOT in "updating" phase (no duplicate noise)
 * - User action explicitly targeted a specialist
 * - That specialist is queued/running
 *
 * Copy format: "Flights · Updating" (noun phrase, no gerunds)
 */
export const SpecialistProgress = memo(function SpecialistProgress({
  status,
}: SpecialistProgressProps) {
  const effectivePhase = deriveEffectivePhase(status);

  // Key rule: hide when global updating (plan header shows that)
  // effectivePhase === 'updating' means the header already shows "Updating"
  if (effectivePhase === 'updating') {
    return null;
  }

  // Only show specialists that are actively running
  const runningSpecialists = status.activeSpecialists.filter((s) => s.state === 'running');

  // If no running specialists, hide
  if (runningSpecialists.length === 0) {
    return null;
  }

  return (
    <div className="flex items-center gap-3 px-3 py-2 border-t border-border/20 bg-muted/10">
      {runningSpecialists.slice(0, 3).map(({ key }) => {
        const Icon = SPECIALIST_ICONS[key];
        const label = SPECIALIST_LABELS[key];

        return (
          <div key={key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Icon className="h-3 w-3 animate-pulse" />
            <span>{label}</span>
            <span className="text-border/60">·</span>
            <span>Updating</span>
          </div>
        );
      })}
    </div>
  );
});
