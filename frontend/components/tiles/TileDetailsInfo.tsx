'use client';

import { MapPin, Star } from 'lucide-react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { ViewMode } from '@/types/plan-envelope';
import type { PartnerPrice, Tile } from '@/types/tile';

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
              <span className="text-zinc-500 dark:text-zinc-500">
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
      {tile.type === 'activity' && tile.meta && (() => {
        const m = tile.meta as Record<string, unknown>;
        const desc = typeof m.description === 'string' && m.description ? m.description : null;
        const category = typeof m.category === 'string' ? m.category : null;
        const duration = typeof m.duration_hours === 'number' ? m.duration_hours : null;
        const timeOfDay = typeof m.time_of_day === 'string' ? m.time_of_day : null;
        const skillLevel = typeof m.skill_level === 'string' && m.skill_level !== 'beginner' ? m.skill_level : null;
        return (
          <div className="space-y-2">
            {desc && (
              <p className="text-sm italic text-zinc-500 dark:text-zinc-400">{desc}</p>
            )}
            <div className="flex flex-wrap gap-1.5">
              {category && (
                <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
                  {category}
                </span>
              )}
              {duration != null && (
                <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-500 dark:text-zinc-400">
                  {duration}h
                </span>
              )}
              {timeOfDay && (
                <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-500 dark:text-zinc-400">
                  {timeOfDay.charAt(0).toUpperCase() + timeOfDay.slice(1)}
                </span>
              )}
              {skillLevel && (
                <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-500 dark:text-zinc-400">
                  {skillLevel.charAt(0).toUpperCase() + skillLevel.slice(1)}
                </span>
              )}
            </div>
          </div>
        );
      })()}

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
              <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-xs text-zinc-500 dark:text-zinc-500">
                +{amenities.length - 8} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* Price block */}
      <div className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800/50 p-3">
        <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          {priceDisplay.perUnit}
        </div>
        {priceDisplay.total && (
          <div className="text-sm text-zinc-500 dark:text-zinc-400">{priceDisplay.total}</div>
        )}
        {tile.provider && (
          <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">
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
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Compare prices
          </h3>
          <div className="space-y-2">
            {partnerPrices.map((pp) => (
              <div
                key={pp.partner}
                className={cn(
                  'flex items-center justify-between p-3 rounded-lg border transition-colors',
                  pp.isBestPrice
                    ? 'border-emerald-500/50 bg-emerald-500/10'
                    : 'border-zinc-200 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800/30 hover:bg-zinc-100 dark:hover:bg-zinc-800/50'
                )}
              >
                <div className="flex items-center gap-3">
                  {pp.logo ? (
                    <img
                      src={pp.logo}
                      alt={pp.partner}
                      className="h-6 w-auto object-contain"
                    />
                  ) : (
                    <span className="text-sm text-zinc-700 dark:text-zinc-300 font-medium">
                      {pp.partner}
                    </span>
                  )}
                  {pp.isBestPrice && (
                    <span className={`px-1.5 py-0.5 rounded ${DS.textSize.micro} font-medium bg-emerald-500/20 text-emerald-400`}>
                      Best Price
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                    {new Intl.NumberFormat('en-US', {
                      style: 'currency',
                      currency: pp.currency,
                      maximumFractionDigits: 0,
                    }).format(pp.price)}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      if (pp.url) {
                        window.open(pp.url, '_blank', 'noopener,noreferrer');
                      }
                      if (tile && onBook) {
                        onBook(tile, pp.partner);
                      }
                    }}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-500 text-white hover:bg-emerald-600 transition-colors"
                  >
                    Book
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
