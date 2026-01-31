/**
 * SafetyBlock
 *
 * Renders safety constraint blocks ("Red Zone") for no-fly buffers,
 * rest days, and acclimatization periods.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

'use client';

import { Mountain, ShieldAlert, Timer } from 'lucide-react';

import { cn } from '@/lib/utils';

interface SafetyBlockProps {
  reason: string;
  until?: string;
  type?: 'no_fly' | 'rest_day' | 'acclimatization';
}

const CONFIG = {
  no_fly: {
    icon: ShieldAlert,
    label: 'Surface Interval',
    description: 'No Flights until',
  },
  rest_day: {
    icon: Timer,
    label: 'Rest Day',
    description: 'Recovery period',
  },
  acclimatization: {
    icon: Mountain,
    label: 'Acclimatization',
    description: 'Altitude adjustment',
  },
};

export function SafetyBlock({ reason, until, type = 'no_fly' }: SafetyBlockProps) {
  const config = CONFIG[type];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        'bg-red-50 dark:bg-red-950/30',
        'border-l-4 border-red-500',
        'p-4 rounded-r-xl'
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className="w-5 h-5 text-red-500" />
        <span className="font-semibold text-red-700 dark:text-red-400">
          {config.label}
        </span>
      </div>
      <p className="mt-1 text-sm text-red-600 dark:text-red-300">
        {reason}
      </p>
      {until && (
        <p className="mt-2 text-xs font-mono font-bold text-red-700 dark:text-red-400">
          {config.description} {until}
        </p>
      )}
    </div>
  );
}
