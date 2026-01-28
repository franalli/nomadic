'use client';

/**
 * TimelineSkeleton
 *
 * Pulsing placeholder shown while the Architect generates the itinerary.
 * Mimics the TimelineThread layout to provide visual continuity.
 */
export function TimelineSkeleton() {
  return (
    <div className="pl-4 pr-2 py-6 space-y-12 relative">
      {/* Thread Line */}
      <div className="absolute left-[31px] top-6 bottom-6 w-0.5 bg-border/50" />

      {[1, 2, 3].map((i) => (
        <div key={i} className="relative z-10 pl-10">
          {/* Day Header Bead */}
          <div className="absolute -left-[1px] top-1 w-9 h-9 rounded-full bg-muted animate-pulse" />

          {/* Day Label */}
          <div className="mb-3 space-y-2">
            <div className="h-5 w-24 bg-muted rounded animate-pulse" />
            <div className="h-3 w-40 bg-muted/60 rounded animate-pulse" />
          </div>

          {/* Content Card */}
          <div className="h-28 w-full bg-muted/30 rounded-xl border border-dashed border-border/50 animate-pulse flex items-center justify-center">
            <div className="text-xs text-muted-foreground/50">
              Building day {i}...
            </div>
          </div>
        </div>
      ))}

      {/* Loading indicator at bottom */}
      <div className="text-center pt-4">
        <p className="text-sm text-muted-foreground animate-pulse">
          Creating your personalized itinerary...
        </p>
      </div>
    </div>
  );
}

export default TimelineSkeleton;
