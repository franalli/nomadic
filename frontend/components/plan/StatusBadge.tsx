'use client';

import { cn } from '@/lib/utils';

const STATE_CONFIG = {
  S1_FRAMING: { label: 'CONFIG READY', active: false },
  S2_STRATEGY_READY: { label: 'STRATEGY READY', active: true },
  S3_ITINERARY_READY: { label: 'ITINERARY READY', active: true },
} as const;

interface StatusBadgeProps {
  state: string;
}

export function StatusBadge({ state }: StatusBadgeProps) {
  const config = STATE_CONFIG[state as keyof typeof STATE_CONFIG];
  if (!config) return null;

  return (
    <div className={cn(
      'flex items-center gap-2 px-3 py-1.5 rounded-full shadow-lg',
      config.active
        // Light: white bg with dark text (matches chat) | Dark: emerald solid
        ? 'bg-white text-zinc-900 dark:bg-emerald-500 dark:text-white'
        : 'bg-black/60 backdrop-blur-sm text-white/90'
    )}>
      {config.active && (
        <div className="h-2 w-2 rounded-full bg-emerald-500 dark:bg-white animate-pulse" />
      )}
      <span className="font-mono text-[10px] uppercase tracking-widest font-bold">
        {config.label}
      </span>
    </div>
  );
}
