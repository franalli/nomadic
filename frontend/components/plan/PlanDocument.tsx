'use client';

import { memo, useMemo } from 'react';

import { cn } from '@/lib/utils';
import { deriveDaysFromFlow, type Conflict } from '@/lib/plan-transform';
import type { DocumentBranch, DocumentTripInputs, PlanStatus } from '@/types/document';
import type { Tile } from '@/types/tile';

import { DaySection } from './DaySection';
import { DocumentHeader } from './DocumentHeader';

// ─────────────────────────────────────────────────────────────────────────────
// ConflictBanner Component
// ─────────────────────────────────────────────────────────────────────────────

interface ConflictBannerProps {
  conflicts: Conflict[];
}

function ConflictBanner({ conflicts }: ConflictBannerProps) {
  if (conflicts.length === 0) return null;

  return (
    <div className="space-y-2">
      {conflicts.map((conflict) => (
        <div
          key={conflict.type}
          className="rounded-lg bg-muted/20 border border-dashed border-muted-foreground/30 p-3"
        >
          <p className="text-xs text-muted-foreground font-medium">
            {conflict.primary}
          </p>
          <p className="text-[10px] text-muted-foreground/70 mt-0.5">
            {conflict.secondary}
          </p>
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PlanDocument Component
// ─────────────────────────────────────────────────────────────────────────────

interface PlanDocumentProps {
  branch: DocumentBranch;
  tiles: Tile[];
  tripInputs: DocumentTripInputs;
  planStatus?: PlanStatus;
  className?: string;
}

function PlanDocumentInner({
  branch,
  tiles,
  tripInputs,
  planStatus,
  className,
}: PlanDocumentProps) {
  const isUpdating = planStatus === 'updating';

  // Derive day-by-day structure from flow
  const planData = useMemo(
    () => deriveDaysFromFlow(branch.flow, tiles, tripInputs),
    [branch.flow, tiles, tripInputs]
  );

  const { days, totalEstimate, hasUnresolvedSegments, conflicts } = planData;

  // No flow data yet
  if (days.length === 0) {
    return (
      <div className={cn('py-6 text-center', className)}>
        <p className="text-muted-foreground text-sm">
          {isUpdating
            ? 'Building your trip plan...'
            : 'Set constraints to generate a day-by-day plan.'}
        </p>
      </div>
    );
  }

  return (
    <div className={cn('space-y-6', className)}>
      {/* Document header with summary */}
      <DocumentHeader
        branch={branch}
        tripInputs={tripInputs}
        totalEstimate={totalEstimate}
        isUpdating={isUpdating}
      />

      {/* Conflict banners - constraint-level conflicts */}
      {!isUpdating && <ConflictBanner conflicts={conflicts} />}

      {/* Unresolved segments warning - plan-level conflict */}
      {hasUnresolvedSegments && !isUpdating && conflicts.length === 0 && (
        <div className="rounded-lg bg-muted/20 border border-dashed border-muted-foreground/30 p-3">
          <p className="text-xs text-muted-foreground">
            Some constraints conflict and prevent a full resolution.
            Adjust constraints to continue.
          </p>
        </div>
      )}

      {/* Day sections */}
      <div className="space-y-6">
        {days.map((day) => (
          <DaySection key={day.dayNumber} day={day} />
        ))}
      </div>

      {/* Price disclaimer */}
      {totalEstimate != null && (
        <p className="text-[10px] text-muted-foreground/60 pt-2 border-t border-border/20">
          Prices are estimates based on current constraints and availability.
        </p>
      )}
    </div>
  );
}

export const PlanDocument = memo(PlanDocumentInner);
