import type { LucideIcon } from 'lucide-react';
import {
  DoorOpen,
  Key,
  PlaneLanding,
  PlaneTakeoff,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const LOGISTICS_THUMBNAIL_CONTAINER = 'h-12 w-12';
export const LOGISTICS_FLIGHT_IMAGE = 'h-8 w-8 object-contain';
export const LOGISTICS_HOTEL_IMAGE = 'h-full w-full object-cover';
export const LOGISTICS_FALLBACK_ICON = 'h-6 w-6';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Constraint object for inline display — derived from DayBlock SSoT */
export type ActiveConstraint = NonNullable<DayBlock['active_constraints']>[number];

export interface LogisticsBlockProps {
  type: 'arrival' | 'departure' | 'checkin' | 'checkout';
  time?: import('./types').DisplayTime;
  details?: string;
  hotelName?: string;
  hotelImage?: string;
  preferenceStatus?: import('./PreferenceAttributionBadge').PreferenceStatus;
  alternativeTileId?: string;
  onSwitchToAlternative?: (tileId: string) => void;
  activeConstraints?: ActiveConstraint[];
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
  deeplinkLabel?: string;
  deeplinkUrl?: string;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export const CONFIG: Record<
  string,
  { icon: LucideIcon; label: string; borderColor: string; bgColor: string; iconColor: string }
> = {
  arrival: {
    icon: PlaneLanding,
    label: 'Arrival',
    borderColor: 'border-emerald-500',
    bgColor: 'bg-emerald-50 dark:bg-emerald-950/20',
    iconColor: 'text-emerald-600 dark:text-emerald-400',
  },
  departure: {
    icon: PlaneTakeoff,
    label: 'Departure',
    borderColor: 'border-zinc-400 dark:border-zinc-500',
    bgColor: 'bg-zinc-50 dark:bg-zinc-800/50',
    iconColor: 'text-zinc-600 dark:text-zinc-400',
  },
  checkin: {
    icon: Key,
    label: 'Check-in',
    borderColor: 'border-blue-500',
    bgColor: 'bg-blue-50 dark:bg-blue-950/20',
    iconColor: 'text-blue-600 dark:text-blue-400',
  },
  checkout: {
    icon: DoorOpen,
    label: 'Check-out',
    borderColor: 'border-zinc-500',
    bgColor: 'bg-zinc-50 dark:bg-zinc-800/50',
    iconColor: 'text-zinc-600 dark:text-zinc-400',
  },
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

export function ConstraintBadges({ constraints }: { constraints: ActiveConstraint[] }) {
  if (constraints.length === 0) return null;

  return (
    <div className="mt-4 space-y-2">
      {constraints.map((constraint) => (
        <div
          key={constraint.id}
          className={cn(
            'flex items-start gap-2 p-3 rounded-lg text-xs',
            constraint.severity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40',
            constraint.severity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40',
            constraint.severity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/40',
            constraint.severity === 'blocking' && 'bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/40'
          )}
        >
          <span className="text-base flex-shrink-0">{constraint.icon}</span>
          <div className="flex-1 min-w-0">
            <div className={cn(
              'font-semibold mb-0.5',
              constraint.severity === 'warning' && 'text-amber-700 dark:text-amber-400',
              constraint.severity === 'info' && 'text-blue-700 dark:text-blue-400',
              constraint.severity === 'success' && 'text-emerald-700 dark:text-emerald-400',
              constraint.severity === 'blocking' && 'text-red-700 dark:text-red-400'
            )}>
              {constraint.title}
            </div>
            <div className="text-zinc-600 dark:text-zinc-400">
              {constraint.description}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
