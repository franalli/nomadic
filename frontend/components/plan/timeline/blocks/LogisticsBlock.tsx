'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * LogisticsBlock
 *
 * Renders hard-time logistics events: arrivals, departures, check-in/out.
 * Shows exact times when available, falls back to time slot badges.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

import {
  DoorOpen,
  ExternalLink,
  Key,
  type LucideIcon,
  PlaneLanding,
  PlaneTakeoff,
  Settings,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, normalizeTitle } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import {
  PreferenceAttributionBadge,
  type PreferenceStatus,
} from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

const LOGISTICS_THUMBNAIL_CONTAINER = 'h-12 w-12';
const LOGISTICS_FLIGHT_IMAGE = 'h-8 w-8 object-contain';
const LOGISTICS_HOTEL_IMAGE = 'h-full w-full object-cover';
const LOGISTICS_FALLBACK_ICON = 'h-6 w-6';

/** Constraint object for inline display — derived from DayBlock SSoT */
type ActiveConstraint = NonNullable<DayBlock['active_constraints']>[number];

interface LogisticsBlockProps {
  type: 'arrival' | 'departure' | 'checkin' | 'checkout';
  time?: DisplayTime;
  details?: string;
  hotelName?: string;
  /** Hotel thumbnail image URL for check-in blocks */
  hotelImage?: string;
  /** Preference attribution for check-in blocks */
  preferenceStatus?: PreferenceStatus;
  alternativeTileId?: string;
  onSwitchToAlternative?: (tileId: string) => void;
  /** Active constraints for inline display */
  activeConstraints?: ActiveConstraint[];
  /** Callback to open stays/hotel settings sheet (for check-in blocks) */
  onOpenStaysSettings?: () => void;
  /** Callback to open flights settings sheet (for arrival/departure blocks) */
  onOpenFlightsSettings?: () => void;
  deeplinkLabel?: string;
  deeplinkUrl?: string;
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

export function LogisticsBlock({
  type,
  time,
  details,
  hotelName,
  hotelImage,
  preferenceStatus,
  alternativeTileId,
  onSwitchToAlternative,
  activeConstraints,
  onOpenStaysSettings,
  onOpenFlightsSettings,
  deeplinkLabel,
  deeplinkUrl,
}: LogisticsBlockProps) {
  const config = CONFIG[type];
  const Icon = config.icon;
  const placeholderFallback = useMemo(
    () =>
      placeholderImageForTile({
        id: hotelName || type,
        type: (type === 'arrival' || type === 'departure') ? 'flight' : 'hotel',
      }),
    [hotelName, type]
  );

  const [resolvedImage, setResolvedImage] = useState(hotelImage);
  const [triedPlaceholder, setTriedPlaceholder] = useState(false);
  const [imageLoadFailed, setImageLoadFailed] = useState(false);

  useEffect(() => {
    setResolvedImage(hotelImage);
    setTriedPlaceholder(false);
    setImageLoadFailed(false);
  }, [hotelImage]);

  // Only show preference badge for check-in blocks (hotels)
  const showPreferenceBadge = type === 'checkin' && preferenceStatus;
  const showImage = Boolean(resolvedImage) && !imageLoadFailed;
  const showFlightDeeplink =
    (type === 'arrival' || type === 'departure') &&
    Boolean(deeplinkUrl && deeplinkUrl !== '#' && deeplinkLabel);

  return (
    <div
      className={cn(
        'group relative flex items-center gap-4 p-3 rounded-lg border-l-4',
        config.borderColor,
        config.bgColor
      )}
    >
      {/* Settings gear for check-in blocks (hotels) - always visible */}
      {type === 'checkin' && onOpenStaysSettings && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onOpenStaysSettings();
          }}
          className={cn(
            'absolute top-2 right-2 p-1.5 rounded-lg transition-all',
            'bg-black/10 hover:bg-black/20 dark:bg-white/10 dark:hover:bg-white/20'
          )}
          aria-label="Hotel settings"
        >
          <Settings className="w-3.5 h-3.5 text-zinc-600 dark:text-zinc-400" />
        </button>
      )}

      {/* Settings gear for flight blocks (arrival/departure) - always visible */}
      {(type === 'arrival' || type === 'departure') && onOpenFlightsSettings && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onOpenFlightsSettings();
          }}
          className={cn(
            'absolute top-2 right-2 p-1.5 rounded-lg transition-all',
            'bg-black/10 hover:bg-black/20 dark:bg-white/10 dark:hover:bg-white/20'
          )}
          aria-label="Flight settings"
        >
          <Settings className="w-3.5 h-3.5 text-zinc-600 dark:text-zinc-400" />
        </button>
      )}
      {/* Shared 48px thumbnail keeps hotel and flight blocks visually aligned in timeline rows */}
      <div className={cn(
        LOGISTICS_THUMBNAIL_CONTAINER,
        'shrink-0 rounded-lg overflow-hidden flex items-center justify-center',
        showImage
          ? (type === 'arrival' || type === 'departure') ? 'bg-white' : 'bg-zinc-200 dark:bg-zinc-700'
          : 'bg-zinc-100 dark:bg-zinc-800'
      )}>
        {showImage ? (
          <img
            src={resolvedImage}
            alt={hotelName || config.label}
            loading="lazy"
            className={(type === 'arrival' || type === 'departure')
              ? LOGISTICS_FLIGHT_IMAGE
              : LOGISTICS_HOTEL_IMAGE
            }
            onError={() => {
              if (!triedPlaceholder) {
                setResolvedImage(placeholderFallback);
                setTriedPlaceholder(true);
                return;
              }
              setImageLoadFailed(true);
            }}
          />
        ) : (
          <Icon className={cn(LOGISTICS_FALLBACK_ICON, config.iconColor)} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {time && (
            time.type === 'exact' ? (
              <span className="font-mono font-bold text-sm text-zinc-900 dark:text-white">{time.value}</span>
            ) : (
              <span className="text-xs px-2 py-0.5 rounded-full bg-white/50 dark:bg-black/20 font-medium text-zinc-700 dark:text-zinc-300">
                {time.value}
              </span>
            )
          )}
          <span className="font-medium text-sm text-zinc-900 dark:text-white">{config.label}</span>
        </div>
        {hotelName && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 truncate">{normalizeTitle(hotelName)}</p>
        )}
        {details && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{details}</p>
        )}
        {showFlightDeeplink && (
          <a
            href={deeplinkUrl}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={deeplinkLabel}
            className={cn(
              DS.actions.smallAction,
              'mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 normal-case tracking-normal',
              'bg-emerald-50 text-emerald-700 hover:bg-emerald-100',
              'dark:bg-emerald-950/40 dark:text-emerald-400 dark:hover:bg-emerald-900/50'
            )}
          >
            {deeplinkLabel}
            <ExternalLink className="h-3 w-3" />
          </a>
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
          <div className="mt-4 space-y-2">
            {activeConstraints.map((constraint) => (
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
        )}
      </div>
    </div>
  );
}
