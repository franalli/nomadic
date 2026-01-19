'use client';

import { Bed, Clock, MapPin, Plane, Train, Umbrella } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { Segment as SegmentData, SegmentType } from '@/lib/plan-transform';

// ─────────────────────────────────────────────────────────────────────────────
// Icon Mapping
// ─────────────────────────────────────────────────────────────────────────────

const SEGMENT_ICONS: Record<SegmentType, typeof Plane> = {
  flight: Plane,
  stay: Bed,
  transfer: Train,
  activity: MapPin,
  free_time: Umbrella,
};

// ─────────────────────────────────────────────────────────────────────────────
// Segment Component
// ─────────────────────────────────────────────────────────────────────────────

interface SegmentProps {
  segment: SegmentData;
  className?: string;
}

function SegmentInner({ segment, className }: SegmentProps) {
  const Icon = SEGMENT_ICONS[segment.type];
  const typeLabel = segment.type.replace('_', ' ');

  return (
    <div
      className={cn(
        'rounded-lg bg-muted/10 border border-border/30 p-3',
        'transition-colors duration-200 hover:bg-muted/20',
        segment.isUnresolved && 'border-dashed border-muted-foreground/30',
        className
      )}
    >
      {/* Type label with icon */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon className="h-3 w-3 text-muted-foreground" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {typeLabel}
        </span>
      </div>

      {/* Primary content */}
      <p className="text-sm font-medium text-foreground leading-snug">
        {segment.primary}
      </p>

      {/* Secondary (duration/details) */}
      {segment.secondary && (
        <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {segment.secondary}
        </p>
      )}

      {/* Tertiary (price) */}
      {segment.tertiary && (
        <p className="text-xs text-muted-foreground mt-1">
          {segment.tertiary}
        </p>
      )}

      {/* Unresolved state */}
      {segment.isUnresolved && (
        <p className="text-xs text-muted-foreground/70 mt-2 italic">
          Segment unresolved — this part of the plan cannot be resolved with current constraints.
        </p>
      )}
    </div>
  );
}

export const Segment = memo(SegmentInner);
