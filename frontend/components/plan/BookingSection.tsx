/**
 * BookingSection
 *
 * Conditional tiles section for the plan view.
 * - S3: Full "Booking options" grid with tabs
 * - S2 with tiles: Collapsed "Deals found" preview (compact list, max 4 items)
 * - S2 without tiles: Minimal placeholder
 * - Other states: Not rendered
 */

'use client';

import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

import { CompactTilesList } from '@/components/tiles/CompactTilesList';
import { TilesGrid } from '@/components/tiles/TilesGrid';
import { getTotalTileCount,selectTilesByType } from '@/lib/tileSelectors';
import type { PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

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

  // S2 with tiles: "Deals found" collapsed preview (compact list, not full TilesGrid)
  if (canShowTilesPreview(state, totalTiles)) {
    // For preview, show stays (hotels) first, max 4 items
    const stayTiles = tileArray.filter(t => t.type === 'hotel' || t.type === 'stay');
    const previewTiles = stayTiles.length > 0 ? stayTiles.slice(0, 4) : tileArray.slice(0, 4);
    const remainingCount = totalTiles - previewTiles.length;

    return (
      <div id="booking-section" className="border-t border-zinc-800">
        {/* Header */}
        <div className="px-4 pt-3 pb-1">
          <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wide">
            Deals found
          </h3>
        </div>

        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex w-full items-center justify-between px-4 py-2 text-sm transition-colors hover:bg-zinc-800/50"
        >
          <div className="flex items-center gap-2">
            <span className="text-zinc-300">{totalTiles} options</span>
            <span className="text-zinc-500">- Preview</span>
          </div>
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-zinc-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-zinc-500" />
          )}
        </button>

        {!isExpanded && (
          <p className="px-4 pb-3 text-xs text-zinc-500">
            Preview only — finalize itinerary to book.
          </p>
        )}

        {isExpanded && (
          <div className="px-4 pb-4">
            <CompactTilesList tiles={previewTiles} />
            {remainingCount > 0 && (
              <p className="text-xs text-zinc-500 mt-2">
                +{remainingCount} more options available after itinerary
              </p>
            )}
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

  // S3: Full "Booking options" section with tabs
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
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-zinc-200">Booking options</h3>
            <span className="text-xs text-zinc-500">({totalTiles})</span>
          </div>
          <span className="text-xs text-zinc-500">Prices from partners</span>
        </div>
        <TilesGrid tiles={tileArray} hideTabSwitcher={false} />
      </div>
    );
  }

  // Other states: don't render (no empty padding)
  return null;
}

export default BookingSection;
