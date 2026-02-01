/**
 * LogisticsBlock
 *
 * Renders hard-time logistics events: arrivals, departures, check-in/out.
 * Shows exact times when available, falls back to time slot badges.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

'use client';

import { DoorOpen, Key, PlaneLanding, PlaneTakeoff, type LucideIcon } from 'lucide-react';

import { cn, normalizeTitle } from '@/lib/utils';

import {
  PreferenceAttributionBadge,
  type PreferenceStatus,
} from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

/** Constraint object for inline display */
interface ActiveConstraint {
  id: string;
  severity: 'warning' | 'info' | 'success';
  icon: string;
  title: string;
  description: string;
}

interface LogisticsBlockProps {
  type: 'arrival' | 'departure' | 'checkin' | 'checkout';
  time?: DisplayTime;
  details?: string;
  hotelName?: string;
  /** Preference attribution for check-in blocks */
  preferenceStatus?: PreferenceStatus;
  alternativeTileId?: string;
  onSwitchToAlternative?: (tileId: string) => void;
  /** Active constraints for inline display */
  activeConstraints?: ActiveConstraint[];
}

const CONFIG: Record<
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
    borderColor: 'border-amber-500',
    bgColor: 'bg-amber-50 dark:bg-amber-950/20',
    iconColor: 'text-amber-600 dark:text-amber-400',
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

export function LogisticsBlock({
  type,
  time,
  details,
  hotelName,
  preferenceStatus,
  alternativeTileId,
  onSwitchToAlternative,
  activeConstraints,
}: LogisticsBlockProps) {
  const config = CONFIG[type];
  const Icon = config.icon;

  // Only show preference badge for check-in blocks (hotels)
  const showPreferenceBadge = type === 'checkin' && preferenceStatus;

  return (
    <div
      className={cn(
        'flex items-center gap-3 p-3 rounded-lg border-l-4',
        config.borderColor,
        config.bgColor
      )}
    >
      <Icon className={cn('w-5 h-5 shrink-0', config.iconColor)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {time && (
            time.type === 'exact' ? (
              <span className="font-mono font-bold text-sm">{time.value}</span>
            ) : (
              <span className="text-xs px-2 py-0.5 rounded-full bg-white/50 dark:bg-black/20 font-medium">
                {time.value}
              </span>
            )
          )}
          <span className="font-medium text-sm">{config.label}</span>
        </div>
        {hotelName && (
          <p className="text-xs text-muted-foreground mt-0.5 truncate">{normalizeTitle(hotelName)}</p>
        )}
        {details && (
          <p className="text-xs text-muted-foreground mt-0.5">{details}</p>
        )}
        {/* Preference attribution badge for check-in blocks */}
        {showPreferenceBadge && (
          <PreferenceAttributionBadge
            status={preferenceStatus}
            alternativeTileId={alternativeTileId}
            onSwitchToAlternative={onSwitchToAlternative}
            className="mt-2"
          />
        )}

        {/* Inline Constraint Badges */}
        {activeConstraints && activeConstraints.length > 0 && (
          <div className="mt-3 space-y-2">
            {activeConstraints.map((constraint) => (
              <div
                key={constraint.id}
                className={cn(
                  'flex items-start gap-2 p-3 rounded-lg text-xs',
                  constraint.severity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40',
                  constraint.severity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40',
                  constraint.severity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/40'
                )}
              >
                <span className="text-base flex-shrink-0">{constraint.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className={cn(
                    'font-semibold mb-0.5',
                    constraint.severity === 'warning' && 'text-amber-700 dark:text-amber-400',
                    constraint.severity === 'info' && 'text-blue-700 dark:text-blue-400',
                    constraint.severity === 'success' && 'text-emerald-700 dark:text-emerald-400'
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
        )}
      </div>
    </div>
  );
}
