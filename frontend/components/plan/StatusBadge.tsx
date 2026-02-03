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
    <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-full bg-black/40 backdrop-blur-sm">
      <div
        className={cn(
          'h-2 w-2 rounded-full',
          config.active
            ? 'bg-emerald-500 animate-pulse'
            : 'bg-white/60'
        )}
      />
      <span className="font-mono text-[10px] uppercase tracking-widest font-bold text-white/90">
        {config.label}
      </span>
    </div>
  );
}
