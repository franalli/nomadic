'use client';

import { Check, Clock, MapPin, Moon, Sun, Sunset } from 'lucide-react';
import type { MouseEvent } from 'react';

import { TaxesFeesTooltip } from '@/components/tiles/TaxesFeesTooltip';
import { CardBody } from '@/components/ui/card';
import { DS } from '@/lib/design-system';
import { renderStarRating } from '@/lib/renderStarRating';
import type { Tile } from '@/types/tile';

import { TileCardActions } from './tileSections';

export interface TileCardContentProps {
  tile: Tile;
  isHotel: boolean;
  activityMeta: {
    category?: string;
    durationHours?: number;
    timeOfDay?: string;
    description?: string;
  } | null;
  amenityIcons: Array<{ icon: string; label: string }>;
  relevanceBadges: string[];
  features: string[];
  onViewDetailsClick: (event: MouseEvent) => void;
}

export function TileCardContent({
  tile,
  isHotel,
  activityMeta,
  amenityIcons,
  relevanceBadges,
  features,
  onViewDetailsClick,
}: TileCardContentProps) {
  return (
    <CardBody className="flex flex-1 flex-col gap-2 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="font-display text-zinc-900 dark:text-white text-lg font-semibold leading-tight">
          {tile.title}
        </div>
        {tile.rating != null && (
          <div className="flex shrink-0 items-center gap-1 text-sm font-medium">
            {isHotel ? (
              <span className="text-zinc-500 dark:text-zinc-300">{renderStarRating(tile.rating)}</span>
            ) : (
              <>
                <span className="text-zinc-500 dark:text-zinc-300">{'\u2605'}</span>
                <span className="text-zinc-900 dark:text-white">{tile.rating.toFixed(1)}</span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Activity metadata badges */}
      {activityMeta && (
        <div className="flex flex-wrap items-center gap-1.5">
          {activityMeta.category && (
            <span className="bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium uppercase tracking-wide">
              {activityMeta.category}
            </span>
          )}
          {activityMeta.durationHours != null && (
            <span className="text-zinc-500 dark:text-zinc-400 inline-flex items-center gap-1 text-xs">
              <Clock className="h-3 w-3" />
              {activityMeta.durationHours}h
            </span>
          )}
          {activityMeta.timeOfDay && (
            <span className="text-zinc-500 dark:text-zinc-400 inline-flex items-center gap-1 text-xs">
              {activityMeta.timeOfDay === 'morning' && <Sun className="h-3 w-3" />}
              {activityMeta.timeOfDay === 'afternoon' && <Sunset className="h-3 w-3" />}
              {activityMeta.timeOfDay === 'evening' && <Moon className="h-3 w-3" />}
              {activityMeta.timeOfDay.charAt(0).toUpperCase() + activityMeta.timeOfDay.slice(1)}
            </span>
          )}
        </div>
      )}

      {/* Activity description */}
      {activityMeta?.description && (
        <p className="text-zinc-500 dark:text-zinc-400 line-clamp-1 text-sm">
          {activityMeta.description}
        </p>
      )}

      {(tile.location_label || amenityIcons.length > 0) && (
        <div className="text-zinc-500 dark:text-zinc-400 -mt-1 flex items-center gap-1.5 text-sm">
          {tile.location_label && (
            <>
              <MapPin className="h-4 w-4 shrink-0" />
              <span className="line-clamp-1">{tile.location_label}</span>
            </>
          )}
          {amenityIcons.length > 0 && (
            <>
              {tile.location_label && <span className="text-zinc-500 dark:text-zinc-400">&middot;</span>}
              <span className="flex gap-0.5">
                {amenityIcons.map(({ icon, label }) => (
                  <span key={label} title={label} >{icon}</span>
                ))}
              </span>
            </>
          )}
        </div>
      )}

      {/* Specialist relevance badges - max 2, shows key attributes */}
      {relevanceBadges.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 -mt-1">
          {relevanceBadges.map((badge) => (
            <span
              key={badge}
              className={`inline-flex items-center gap-1 ${DS.textSize.badgeLabel} text-zinc-400`}
            >
              <Check className="h-3 w-3 text-emerald-500" />
              {badge}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {features.map((feature) => (
          <span
            key={feature}
            className="bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium"
          >
            {feature}
          </span>
        ))}
      </div>

      <div className="mt-auto flex items-end justify-between pt-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-zinc-500 dark:text-zinc-400 text-xs">
            {tile.total_inclusive != null ? 'Total from' : 'From'}
          </span>
          <div className="flex items-baseline gap-1">
            <span className={`text-zinc-900 dark:text-zinc-100 ${DS.textSize.priceDisplay} font-semibold`}>
              {(tile.total_inclusive ?? tile.price_estimate) != null
                ? Math.round(tile.total_inclusive ?? tile.price_estimate!).toLocaleString()
                : ''}
            </span>
            <span className="text-zinc-500 dark:text-zinc-400 text-sm font-medium">{tile.currency}</span>
            {tile.type?.toLowerCase().includes('stay') && !tile.total_inclusive && (
              <span className="text-zinc-500 dark:text-zinc-400 text-xs">/night</span>
            )}
          </div>
          {(tile.total_inclusive ?? tile.price_estimate) == null && (
            <span className="text-zinc-900 dark:text-zinc-100 text-sm font-semibold">Check price</span>
          )}
          {/* Expedia taxes & fees disclosure with legal tooltip */}
          <TaxesFeesTooltip
            taxAndServiceFee={tile.tax_and_service_fee}
            propertyFee={tile.property_fee}
            currency={tile.currency}
          />
        </div>
        <TileCardActions tile={tile} onViewDetailsClick={onViewDetailsClick} />
      </div>
    </CardBody>
  );
}
