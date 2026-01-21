/**
 * BookingSection
 *
 * Conditional tiles section for the plan view.
 * - S3: Full expanded tiles grid
 * - S2 with tiles: Collapsed preview (one-line summary)
 * - S2 without tiles: Minimal placeholder
 * - Other states: Not rendered
 */

'use client';

import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { TilesGrid } from '@/components/tiles/TilesGrid';
import { selectTilesByType, getTotalTileCount } from '@/lib/tileSelectors';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';
import type { PlanViewState } from '@/types/plan-envelope';

import { canShowBookingTiles, canShowTilesPreview } from './planStateHelpers';

export interface BookingSectionProps {
  state: PlanViewState;
  tiles: Record<string, Tile> | Tile[];
}

export function BookingSection({ state, tiles }: BookingSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Convert tiles to array if needed
  const tileArray = Array.isArray(tiles) ? tiles : Object.values(tiles);
  const tilesByType = selectTilesByType(tiles);
  const totalTiles = getTotalTileCount(tilesByType);

  // S2 with tiles: subtle collapsed preview (YC: don't clutter)
  if (canShowTilesPreview(state, totalTiles)) {
    return (
      <div id="booking-section" className="border-t border-zinc-800">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex w-full items-center justify-between px-4 py-2 text-sm text-zinc-500 transition-colors hover:text-zinc-400"
        >
          <span>{totalTiles} booking options found</span>
          {isExpanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>

        {isExpanded && (
          <div className="px-4 pb-4">
            <TilesGrid tiles={tileArray} hideTabSwitcher={false} />
          </div>
        )}
      </div>
    );
  }

  // S2 without tiles: minimal 1-line placeholder (no heavy borders)
  if (state.startsWith('S2_')) {
    return (
      <div id="booking-section" className="px-4 py-2">
        <p className="text-xs text-zinc-600">
          Booking options appear after itinerary.
        </p>
      </div>
    );
  }

  // S3: Full section
  if (canShowBookingTiles(state)) {
    if (totalTiles === 0) {
      return (
        <div id="booking-section" className="border-t border-zinc-800 p-4">
          <p className="text-sm text-zinc-500">No booking options available yet.</p>
        </div>
      );
    }

    return (
      <div id="booking-section" className="border-t border-zinc-800 p-4">
        <TilesGrid tiles={tileArray} hideTabSwitcher={false} />
      </div>
    );
  }

  // Other states: don't render (no empty padding)
  return null;
}

export default BookingSection;
