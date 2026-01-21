'use client';

import { memo } from 'react';

import type { DayData } from '@/lib/plan-transform';
import { cn } from '@/lib/utils';

import { Segment } from './Segment';

// ─────────────────────────────────────────────────────────────────────────────
// DaySection Component
// ─────────────────────────────────────────────────────────────────────────────

interface DaySectionProps {
  day: DayData;
  className?: string;
}

function DaySectionInner({ day, className }: DaySectionProps) {
  const dateFormatter = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  });

  const dateLabel = day.date ? dateFormatter.format(day.date) : null;

  return (
    <section className={cn('border-t border-border/30 pt-4', className)}>
      {/* Day header */}
      <div className="flex items-baseline gap-2 mb-3">
        <h4 className="text-sm font-bold uppercase tracking-wide text-foreground">
          Day {day.dayNumber}
        </h4>
        {day.dayOfWeek && (
          <span className="text-xs text-muted-foreground">
            · {day.dayOfWeek}
          </span>
        )}
        {dateLabel && (
          <span className="text-xs text-muted-foreground">
            · {dateLabel}
          </span>
        )}
      </div>

      {/* Segments */}
      <div className="space-y-2">
        {day.segments.length > 0 ? (
          day.segments.map((segment, idx) => (
            <Segment key={idx} segment={segment} />
          ))
        ) : (
          <p className="text-sm text-muted-foreground italic">
            No activities planned for this day.
          </p>
        )}
      </div>

      {/* Day notes */}
      {day.notes && (
        <p className="text-xs text-muted-foreground mt-3 italic">
          {day.notes}
        </p>
      )}
    </section>
  );
}

export const DaySection = memo(DaySectionInner);
