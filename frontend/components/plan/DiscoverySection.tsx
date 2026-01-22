/**
 * DiscoverySection
 *
 * S2 Plan stage - shows "Options to choose from" with mini-cards.
 * Users can save options to shortlist before creating itinerary.
 *
 * Layout:
 * - Header: "Options to choose from" + Shortlist (n) pill
 * - Subtitle: "Shortlist options now. We'll build the itinerary next, then unlock booking links."
 * - MiniCard grid for tiles
 * - CTA: "Create day-by-day itinerary" (in NextStepBar, not here)
 */

'use client';

import { Heart } from 'lucide-react';
import { memo, useCallback, useMemo, useState } from 'react';

import { MiniCard } from '@/components/tiles/MiniCard';
import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface DiscoverySectionProps {
  /** All tiles keyed by ID */
  tiles: Record<string, Tile>;
  /** IDs of saved/shortlisted tiles */
  savedTileIds: Set<string>;
  /** Count of saved stays specifically */
  savedStaysCount: number;
  /** Whether we're in S3 (itinerary ready, booking unlocked) */
  isBookingUnlocked?: boolean;
  /** Callback when user clicks Save on a tile */
  onSaveTile: (tile: Tile) => void;
  /** Callback to open shortlist drawer */
  onOpenShortlist?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Category Labels
// ─────────────────────────────────────────────────────────────────────────────

// Reserved for future use - get user-facing category label
function _getCategoryLabel(tileType: string): string {
  const type = tileType.toLowerCase();
  if (type.includes('stay') || type.includes('hotel')) return 'Stays';
  if (type.includes('flight')) return 'Flights';
  if (type.includes('activity')) return 'Activities';
  return 'Options';
}
void _getCategoryLabel;

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export const DiscoverySection = memo(function DiscoverySection({
  tiles,
  savedTileIds,
  savedStaysCount: _savedStaysCount,
  isBookingUnlocked = false,
  onSaveTile,
  onOpenShortlist,
}: DiscoverySectionProps) {
  // Reserved for future use
  void _savedStaysCount;
  // Modal state for tile details
  const [selectedTile, setSelectedTile] = useState<Tile | null>(null);

  // Group tiles by category
  const groupedTiles = useMemo(() => {
    const tileArray = Object.values(tiles);
    const groups: Record<string, Tile[]> = {
      stays: [],
      flights: [],
      activities: [],
    };

    for (const tile of tileArray) {
      const type = (tile.type || '').toLowerCase();
      if (type.includes('stay') || type.includes('hotel')) {
        groups.stays.push(tile);
      } else if (type.includes('flight')) {
        groups.flights.push(tile);
      } else if (type.includes('activity')) {
        groups.activities.push(tile);
      }
    }

    // Sort saved items first within each group
    for (const key of Object.keys(groups)) {
      groups[key].sort((a, b) => {
        const aIsSaved = savedTileIds.has(a.id);
        const bIsSaved = savedTileIds.has(b.id);
        if (aIsSaved && !bIsSaved) return -1;
        if (!aIsSaved && bIsSaved) return 1;
        return 0;
      });
    }

    return groups;
  }, [tiles, savedTileIds]);

  // Total saved count
  const totalSavedCount = savedTileIds.size;

  // Handlers
  const handleDetailsClick = useCallback((tile: Tile) => {
    setSelectedTile(tile);
  }, []);

  const handleCloseDetails = useCallback(() => {
    setSelectedTile(null);
  }, []);

  const handleSaveClick = useCallback(
    (tile: Tile) => {
      onSaveTile(tile);
    },
    [onSaveTile]
  );

  // If no tiles, show empty state
  const hasTiles =
    groupedTiles.stays.length > 0 ||
    groupedTiles.flights.length > 0 ||
    groupedTiles.activities.length > 0;

  if (!hasTiles) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-6">
        <p className="text-sm text-zinc-500">
          Options will appear here once your plan is generated.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">
            Options to choose from
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            Shortlist options now. We'll build the itinerary next, then unlock booking links.
          </p>
        </div>

        {/* Shortlist pill */}
        {onOpenShortlist && (
          <button
            type="button"
            onClick={onOpenShortlist}
            className={cn(
              'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors',
              totalSavedCount > 0
                ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
            )}
          >
            <Heart
              className={cn('h-4 w-4', totalSavedCount > 0 && 'fill-amber-400')}
            />
            Shortlist ({totalSavedCount})
          </button>
        )}
      </div>

      {/* Tile groups */}
      <div className="space-y-6">
        {/* Stays */}
        {groupedTiles.stays.length > 0 && (
          <TileGroup
            label="Stays"
            tiles={groupedTiles.stays}
            savedTileIds={savedTileIds}
            isBookingUnlocked={isBookingUnlocked}
            onDetailsClick={handleDetailsClick}
            onSaveClick={handleSaveClick}
          />
        )}

        {/* Flights */}
        {groupedTiles.flights.length > 0 && (
          <TileGroup
            label="Flights"
            tiles={groupedTiles.flights}
            savedTileIds={savedTileIds}
            isBookingUnlocked={isBookingUnlocked}
            onDetailsClick={handleDetailsClick}
            onSaveClick={handleSaveClick}
          />
        )}

        {/* Activities */}
        {groupedTiles.activities.length > 0 && (
          <TileGroup
            label="Activities"
            tiles={groupedTiles.activities}
            savedTileIds={savedTileIds}
            isBookingUnlocked={isBookingUnlocked}
            onDetailsClick={handleDetailsClick}
            onSaveClick={handleSaveClick}
          />
        )}
      </div>

      {/* Details Modal */}
      {selectedTile && (
        <TileDetailsModal
          tile={selectedTile}
          isOpen={true}
          onClose={handleCloseDetails}
          isSaved={savedTileIds.has(selectedTile.id)}
          onSaveClick={() => handleSaveClick(selectedTile)}
        />
      )}
    </div>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// TileGroup Component
// ─────────────────────────────────────────────────────────────────────────────

interface TileGroupProps {
  label: string;
  tiles: Tile[];
  savedTileIds: Set<string>;
  isBookingUnlocked: boolean;
  onDetailsClick: (tile: Tile) => void;
  onSaveClick: (tile: Tile) => void;
}

const TileGroup = memo(function TileGroup({
  label,
  tiles,
  savedTileIds,
  isBookingUnlocked,
  onDetailsClick,
  onSaveClick,
}: TileGroupProps) {
  // Show preview label when booking is NOT unlocked (S2 discovery mode)
  const showPreviewLabel = !isBookingUnlocked;

  return (
    <div>
      <h3 className="mb-2 text-sm font-medium text-zinc-400">{label}</h3>
      <div className="space-y-2">
        {tiles.slice(0, 5).map((tile) => (
          <MiniCard
            key={tile.id}
            tile={tile}
            isSaved={savedTileIds.has(tile.id)}
            showPreviewLabel={showPreviewLabel}
            isBookingUnlocked={isBookingUnlocked}
            onDetailsClick={onDetailsClick}
            onSaveClick={onSaveClick}
          />
        ))}
        {tiles.length > 5 && (
          <p className="text-xs text-zinc-500">
            +{tiles.length - 5} more options
          </p>
        )}
      </div>
    </div>
  );
});

export default DiscoverySection;
