'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */

import {
  ExternalLink,
  Settings,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, normalizeTitle } from '@/lib/utils';

import {
  CONFIG,
  ConstraintBadges,
  LOGISTICS_FALLBACK_ICON,
  LOGISTICS_FLIGHT_IMAGE,
  LOGISTICS_HOTEL_IMAGE,
  LOGISTICS_THUMBNAIL_CONTAINER,
  type LogisticsBlockProps,
} from './logisticsBlockParts';
import {
  PreferenceAttributionBadge,
} from './PreferenceAttributionBadge';

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
          <ConstraintBadges constraints={activeConstraints} />
        )}
      </div>
    </div>
  );
}
