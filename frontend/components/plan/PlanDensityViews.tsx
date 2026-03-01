'use client';

/**
 * PlanDensityViews — Mirror-loader density view.
 * @see docs/ux_unified_architecture.md Section VII - Data Density Levels
 */

import { TimelineSkeleton } from './timeline/TimelineSkeleton';

export function PlanMirrorLoader({ tripDuration }: { tripDuration: number }) {
  return (
    <div className="p-4 space-y-6">
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
        <span className="text-sm text-zinc-500 dark:text-zinc-400">Searching live availability...</span>
      </div>
      <TimelineSkeleton />
      <p className="text-xs text-zinc-500 dark:text-zinc-400 text-center">
        Finding flights and hotels for your {tripDuration}-day trip
      </p>
    </div>
  );
}
