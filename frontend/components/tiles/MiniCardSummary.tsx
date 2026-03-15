'use client';

import { Clock, Heart, Moon, Sun, Sunset } from 'lucide-react';
import type { MouseEvent } from 'react';
import { useMemo } from 'react';

import { DS } from '@/lib/design-system';
import { renderStarRating } from '@/lib/renderStarRating';
import { cn, isHotelType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { MiniCardSummaryPricing } from './MiniCardSummaryPricing';
import { MiniCardSummaryThumbnail } from './MiniCardSummaryThumbnail';
import {
  getAmenityIconsWithLabels,
  getTileActivityMeta,
} from './tileHelpers';

type MiniCardSummaryProps = {
  tile: Tile;
  isSaved: boolean;
  perks: string[];
  onSaveClick: (event: MouseEvent) => void;
  onOpenStaysSettings?: () => void;
  saveLabel?: string;
};

export function MiniCardSummary({
  tile,
  isSaved,
  perks,
  onSaveClick,
  onOpenStaysSettings,
  saveLabel,
}: MiniCardSummaryProps) {
  const amenityIcons = useMemo(() => getAmenityIconsWithLabels(tile), [tile]);
  const activityMeta = useMemo(() => getTileActivityMeta(tile), [tile]);

  return (
    <div className="flex items-start gap-4 p-4">
      <MiniCardSummaryThumbnail tile={tile} onOpenStaysSettings={onOpenStaysSettings} />

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-start justify-between gap-2">
          <h4 className="line-clamp-1 text-sm font-medium text-zinc-900 dark:text-zinc-100">
            {tile.title}
          </h4>
          <div className="flex shrink-0 items-center gap-2">
            {tile.rating != null && (
              <div className="flex items-center gap-0.5 text-xs">
                {isHotelType(tile.type || '') ? (
                  <span className="text-zinc-500 dark:text-zinc-300">
                    {renderStarRating(tile.rating)}
                  </span>
                ) : (
                  <>
                    <span className="text-zinc-500 dark:text-zinc-300">{'\u2605'}</span>
                    <span className="text-zinc-500 dark:text-zinc-400">
                      {tile.rating.toFixed(1)}
                    </span>
                  </>
                )}
              </div>
            )}
            <button
              type="button"
              onClick={onSaveClick}
              className={cn(
                'flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors',
                isSaved
                  ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                  : 'text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100'
              )}
            >
              <Heart className={cn('h-3 w-3', isSaved && 'fill-emerald-400')} />
              {isSaved ? 'In Trip' : (saveLabel ?? 'Add to Trip')}
            </button>
          </div>
        </div>

        {(tile.location_label || amenityIcons.length > 0) && (
          <div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            {tile.location_label && <span className="line-clamp-1">{tile.location_label}</span>}
            {amenityIcons.length > 0 && (
              <>
                {tile.location_label && (
                  <span className="text-zinc-400 dark:text-zinc-500">&middot;</span>
                )}
                <span className="flex gap-0.5">
                  {amenityIcons.map(({ icon, label }) => (
                    <span key={label} title={label}>
                      {icon}
                    </span>
                  ))}
                </span>
              </>
            )}
          </div>
        )}

        {activityMeta && (
          <div className="flex flex-wrap items-center gap-1.5">
            {activityMeta.category && (
              <span
                className={`rounded px-1.5 py-0.5 ${DS.textSize.micro} font-medium uppercase tracking-wide bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400`}
              >
                {activityMeta.category}
              </span>
            )}
            {activityMeta.durationHours != null && (
              <span
                className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-400 inline-flex items-center gap-0.5`}
              >
                <Clock className="h-2.5 w-2.5" />
                {activityMeta.durationHours}h
              </span>
            )}
            {activityMeta.timeOfDay && (
              <span
                className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-400 inline-flex items-center gap-0.5`}
              >
                {activityMeta.timeOfDay === 'morning' && <Sun className="h-2.5 w-2.5" />}
                {activityMeta.timeOfDay === 'afternoon' && <Sunset className="h-2.5 w-2.5" />}
                {activityMeta.timeOfDay === 'evening' && <Moon className="h-2.5 w-2.5" />}
                {activityMeta.timeOfDay.charAt(0).toUpperCase() + activityMeta.timeOfDay.slice(1)}
              </span>
            )}
          </div>
        )}

        {activityMeta?.description && (
          <p className={`${DS.textSize.mini} line-clamp-1 text-zinc-500 dark:text-zinc-400`}>
            {activityMeta.description}
          </p>
        )}

        {perks.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {perks.map((perk) => (
              <span
                key={perk}
                className={cn(
                  `rounded px-1.5 py-0.5 ${DS.textSize.micro} font-medium`,
                  perk === 'Free cancel'
                    ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400'
                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400'
                )}
              >
                {perk}
              </span>
            ))}
          </div>
        )}

        <MiniCardSummaryPricing tile={tile} />
      </div>
    </div>
  );
}
