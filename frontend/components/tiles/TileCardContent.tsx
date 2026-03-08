'use client';

import { Check, Clock, ExternalLink, MapPin, Moon, Sun, Sunset } from 'lucide-react';
import type { MouseEvent } from 'react';

import { TaxesFeesTooltip } from '@/components/tiles/TaxesFeesTooltip';
import { Button } from '@/components/ui/button';
import { CardBody } from '@/components/ui/card';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { DS } from '@/lib/design-system';
import { renderStarRating } from '@/lib/renderStarRating';
import { getDeepLinkParams } from '@/lib/tileUtils';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

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
              {tile.location_label && <span className="text-zinc-500">&middot;</span>}
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
            className="bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium"
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
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            <TooltipProvider delayDuration={400}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white"
                    onClick={onViewDetailsClick}
                  >
                    Details
                  </Button>
                </TooltipTrigger>
                <TooltipContent
                  side="top"
                  className="max-w-xs bg-zinc-900 text-zinc-100 text-xs font-mono p-3 rounded-lg shadow-lg"
                >
                  <div className={`text-zinc-400 ${DS.textSize.micro} uppercase tracking-wider mb-1.5`}>
                    API Params
                  </div>
                  <pre className="whitespace-pre-wrap break-all">
                    {JSON.stringify(getDeepLinkParams(tile), null, 2)}
                  </pre>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            {tile.deeplink_url && tile.deeplink_url !== '#' && (() => {
              const isViator = tile.deeplink_url.includes('viator.com');
              const isGYG = tile.deeplink_url.includes('getyourguide.com');
              const isPartner = isViator || isGYG;
              return (
                <a
                  href={tile.deeplink_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e: MouseEvent) => e.stopPropagation()}
                  className={cn(
                    'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                    'text-xs font-bold uppercase tracking-wide',
                    'transition-all duration-150 active:scale-95',
                    'bg-emerald-50 border border-emerald-500/30 text-emerald-700',
                    'hover:bg-emerald-100 hover:border-emerald-500/60',
                    'dark:bg-emerald-950/40 dark:border-emerald-500/25 dark:text-emerald-400',
                    'dark:hover:bg-emerald-900/50 dark:hover:border-emerald-400/50',
                    'dark:hover:shadow-[0_0_16px_-3px_rgba(16,185,129,0.35)]',
                  )}
                >
                  {isPartner ? <ExternalLink className="w-3.5 h-3.5" /> : <MapPin className="w-3.5 h-3.5" />}
                  {isPartner ? 'Book' : 'Map'}
                </a>
              );
            })()}
          </div>
        </div>
      </div>
    </CardBody>
  );
}
