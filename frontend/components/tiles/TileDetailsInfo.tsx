'use client';

import { MapPin, Star } from 'lucide-react';

import { DS } from '@/lib/design-system';
import type { ViewMode } from '@/types/plan-envelope';
import type { PartnerPrice, Tile } from '@/types/tile';

import { TileDetailsActivitySection, TileDetailsPartnerPrices } from './tileSections';

export interface TileDetailsInfoProps {
  tile: Tile;
  isFlight: boolean;
  mode: ViewMode;
  /** Rating and location display data */
  reviewCount: number | null;
  /** Key facts data */
  checkTimes: { checkIn?: string; checkOut?: string };
  cancellationText: string | null;
  /** Price display */
  priceDisplay: { perUnit: string; total?: string };
  /** Amenities list */
  amenities: string[];
  /** AI reasoning (PLANNING mode) */
  aiReasoning: string | null;
  aiPick: boolean;
  /** Partner prices (BOOKING mode) */
  partnerPrices?: PartnerPrice[];
  onBook?: (tile: Tile, partner: string) => void;
}

export function TileDetailsInfo({
  tile,
  isFlight,
  mode,
  reviewCount,
  checkTimes,
  cancellationText,
  priceDisplay,
  amenities,
  aiReasoning,
  aiPick,
  partnerPrices,
  onBook,
}: TileDetailsInfoProps) {
  return (
    <div className="space-y-4 p-4">
      {/* Rating and location row */}
      <div className="flex items-center justify-between text-sm">
        {tile.rating != null && (
          <div className="flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300">
            <Star className="h-4 w-4 fill-zinc-400 text-zinc-500 dark:text-zinc-400" />
            <span className="font-medium">{tile.rating.toFixed(1)}</span>
            {reviewCount != null && (
              <span className="text-zinc-500 dark:text-zinc-400">
                ({reviewCount} reviews)
              </span>
            )}
          </div>
        )}
        {tile.location_label && (
          <div className="flex items-center gap-1 text-zinc-500 dark:text-zinc-400">
            <MapPin className="h-4 w-4" />
            <span>{tile.location_label}</span>
          </div>
        )}
      </div>

      {/* Key facts */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Key facts</h3>
        <ul className="space-y-1 text-sm text-zinc-500 dark:text-zinc-400">
          {checkTimes.checkIn && (
            <li>&#8226; Check-in: {checkTimes.checkIn}</li>
          )}
          {checkTimes.checkOut && (
            <li>&#8226; Check-out: {checkTimes.checkOut}</li>
          )}
          {cancellationText && <li>&#8226; {cancellationText}</li>}
          {isFlight && tile.meta && (
            <>
              {typeof (tile.meta as Record<string, unknown>).stops ===
                'string' && (
                <li>
                  &#8226; {String((tile.meta as Record<string, unknown>).stops)}
                </li>
              )}
              {typeof (tile.meta as Record<string, unknown>).duration ===
                'string' && (
                <li>
                  &#8226; Duration:{' '}
                  {String((tile.meta as Record<string, unknown>).duration)}
                </li>
              )}
            </>
          )}
        </ul>
      </div>

      {/* Activity metadata */}
      {tile.type === 'activity' && tile.meta && <TileDetailsActivitySection tile={tile} />}

      {/* Amenities */}
      {amenities.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Amenities</h3>
          <div className="flex flex-wrap gap-1.5">
            {amenities.slice(0, 8).map((amenity) => (
              <span
                key={amenity}
                className="rounded bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-500 dark:text-zinc-400"
              >
                {amenity}
              </span>
            ))}
            {amenities.length > 8 && (
              <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-500 dark:text-zinc-400">
                +{amenities.length - 8} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* Price block */}
      <div className="rounded-lg border border-zinc-200 dark:border-white/10 bg-zinc-100 dark:bg-zinc-800/50 p-3">
        <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          {priceDisplay.perUnit}
        </div>
        {priceDisplay.total && (
          <div className="text-sm text-zinc-500 dark:text-zinc-400">{priceDisplay.total}</div>
        )}
        {tile.provider && (
          <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            via {tile.provider}
          </div>
        )}
      </div>

      {/* MODE-SPECIFIC SECTIONS */}

      {/* PLANNING mode: "Why this?" AI reasoning section */}
      {mode === 'planning' && (aiReasoning || aiPick) && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-sm">&#10024;</span>
            <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
              Why this suggestion?
            </h3>
            {aiPick && (
              <span className={`px-1.5 py-0.5 rounded ${DS.textSize.micro} font-medium bg-emerald-500/20 text-emerald-400`}>
                AI Pick
              </span>
            )}
          </div>
          {aiReasoning && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
              {aiReasoning}
            </p>
          )}
        </div>
      )}

      {/* BOOKING mode: Partner price comparison */}
      {mode === 'booking' && partnerPrices && partnerPrices.length > 0 && (
        <TileDetailsPartnerPrices tile={tile} partnerPrices={partnerPrices} onBook={onBook} />
      )}
    </div>
  );
}
