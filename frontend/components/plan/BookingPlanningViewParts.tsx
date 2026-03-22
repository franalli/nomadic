'use client';

/**
 * BookingPlanningViewParts — Extracted sub-components for BookingPlanningView.
 */

import { Lock } from 'lucide-react';

import { DS } from '@/lib/design-system';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { SuggestionCard } from './tiles/SuggestionCard';
import { TileRailCard } from './tiles/TileRailCard';

interface BookingSectionGroupProps {
  title: 'Stays' | 'Flights' | 'Activities';
  tiles: Tile[];
  emptyMessage: string;
  savedTileIds: Set<string>;
  onSave: (tile: Tile) => void;
  onDetailsClick: (tile: Tile) => void;
  onViewAlternatives?: (tile: Tile) => void;
  onOpenStaysSettings?: () => void;
}

/** Lock message shown when dates are not set. */
export function BookingLockMessage({ onOpenSheet }: { onOpenSheet?: (sheet: SheetType) => void }) {
  return (
    <p className="mt-2 flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
      <Lock className="h-3 w-3" />
      <span>
        Booking links unlock after you{' '}
        {onOpenSheet ? (
          <button
            type="button"
            onClick={() => onOpenSheet('dates')}
            className="text-emerald-700 underline underline-offset-2 hover:text-emerald-800 dark:text-emerald-400 dark:hover:text-emerald-300"
          >
            set trip dates
          </button>
        ) : (
          'set trip dates'
        )}{' '}
        and create your itinerary.
      </span>
    </p>
  );
}

/** Renders a single category group (Stays/Flights as rail, Activities as list). */
export function BookingSectionGroup({
  title,
  tiles,
  emptyMessage,
  savedTileIds,
  onSave,
  onDetailsClick,
  onViewAlternatives,
  onOpenStaysSettings,
}: BookingSectionGroupProps) {
  const isRail = title === 'Stays' || title === 'Flights';

  return (
    <section aria-label={`${title.toLowerCase()} suggestions`}>
      <h2 className={`${DS.text.label} mb-3`}>{title}</h2>
      {tiles.length > 0 ? (
        isRail ? (
          <div className="flex gap-3 overflow-x-auto pb-2 snap-x snap-mandatory -mx-1 px-1">
            {tiles.slice(0, 6).map((tile) => (
              <TileRailCard
                key={tile.id}
                tile={tile}
                isSaved={savedTileIds.has(tile.id)}
                onSave={onSave}
                onDetailsClick={onDetailsClick}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            {tiles.slice(0, 6).map((tile) => (
              <SuggestionCard
                key={tile.id}
                tile={tile}
                reasoning={tile.meta?.reasoning as string | undefined}
                isSaved={savedTileIds.has(tile.id)}
                onSave={onSave}
                onViewAlternatives={onViewAlternatives ? () => onViewAlternatives(tile) : undefined}
                onDetailsClick={onDetailsClick}
                onOpenStaysSettings={onOpenStaysSettings}
                variant="compact"
              />
            ))}
            {tiles.length > 6 && (
              <p className="pt-2 text-xs text-zinc-500 dark:text-zinc-400">
                +{tiles.length - 6} more {title.toLowerCase()} available
              </p>
            )}
          </div>
        )
      ) : (
        <p className="py-2 text-xs text-zinc-500 dark:text-zinc-400">{emptyMessage}</p>
      )}
    </section>
  );
}
