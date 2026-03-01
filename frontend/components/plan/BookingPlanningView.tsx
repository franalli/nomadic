'use client';

/**
 * BookingPlanningView — Planning-mode tile rendering for BookingSection.
 *
 * Shows SuggestionCards grouped by stays/flights/activities with save,
 * alternatives, and details actions. This is the S2-style preview
 * regardless of S2/S3 state.
 *
 * @see docs/ux_unified_architecture.md Section I.B - Booking Suggestions Pattern
 */

import { Lock } from 'lucide-react';
import { useCallback, useState } from 'react';

import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { ViewMode } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { AlternativesModal } from './modals/AlternativesModal';
import { SuggestionCard } from './tiles/SuggestionCard';

interface BookingPlanningViewProps {
  /** Filtered stay tiles (after applyFilters) */
  filteredStayTiles: Tile[];
  /** Filtered flight tiles (after applyFilters) */
  filteredFlightTiles: Tile[];
  /** Filtered activity tiles (after applyFilters) */
  filteredActivityTiles: Tile[];
  /** All tiles as array (for alternatives lookup) */
  tileArray: Tile[];
  /** Set of saved/preferred tile IDs */
  savedTileIds: Set<string>;
  /** Whether stays/activities section is expanded */
  isExpanded: boolean;
  /** Whether flights section is expanded */
  flightsExpanded: boolean;
  /** Whether trip dates are set */
  hasDates: boolean;
  /** Effective view mode */
  effectiveMode: ViewMode;
  /** Callback when user clicks Save on a tile */
  onSaveTile?: (tile: Tile) => void;
  /** Callback to open a sheet */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Callback when user wants to view alternatives for a tile */
  onViewAlternatives?: (tile: Tile) => void;
  /** Callback to open stays/hotel settings sheet */
  onOpenStaysSettings?: () => void;
}

export function BookingPlanningView({
  filteredStayTiles,
  filteredFlightTiles,
  filteredActivityTiles,
  tileArray,
  savedTileIds,
  isExpanded,
  flightsExpanded,
  hasDates,
  effectiveMode,
  onSaveTile,
  onOpenSheet,
  onViewAlternatives,
  onOpenStaysSettings,
}: BookingPlanningViewProps) {
  const [selectedTile, setSelectedTile] = useState<Tile | null>(null);
  const [alternativesTile, setAlternativesTile] = useState<Tile | null>(null);

  const handleDetailsClick = useCallback((tile: Tile) => {
    setSelectedTile(tile);
  }, []);

  const handleSaveClick = useCallback(
    (tile: Tile) => {
      onSaveTile?.(tile);
    },
    [onSaveTile]
  );

  const handleCloseModal = useCallback(() => {
    setSelectedTile(null);
  }, []);

  const handleViewAlternatives = useCallback((tile: Tile) => {
    if (onViewAlternatives) {
      onViewAlternatives(tile);
    } else {
      setAlternativesTile(tile);
    }
  }, [onViewAlternatives]);

  const handleCloseAlternatives = useCallback(() => {
    setAlternativesTile(null);
  }, []);

  const handleSelectAlternative = useCallback((tile: Tile) => {
    onSaveTile?.(tile);
    setAlternativesTile(null);
  }, [onSaveTile]);

  const getAlternatives = useCallback((tile: Tile): Tile[] => {
    return tileArray.filter(t =>
      t.id !== tile.id &&
      t.type === tile.type
    );
  }, [tileArray]);

  const stayTiles = filteredStayTiles;
  const flightTiles = filteredFlightTiles;

  return (
    <ModalErrorBoundary>
      <div id="booking-section">
        <div className="px-6 pt-0 pb-1">
          {savedTileIds.size > 0 && (
            <span
              className={cn(
                'mt-2 inline-flex items-center rounded-full bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700 dark:bg-emerald-900/10 dark:text-emerald-300',
                DS.textSize.micro
              )}
            >
              {savedTileIds.size} in trip
            </span>
          )}
          {/* Section-level lock message - only show if dates are NOT set */}
          {/* @see docs/ux_unified_architecture.md Section XII - Tiles-first logic */}
          {!hasDates && (
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
          )}
        </div>

        {/* Stays tiles */}
        {isExpanded && (
          <div className="px-6 pb-4 space-y-4">
            {stayTiles.length > 0 ? (
              <>
                {stayTiles.slice(0, 6).map((tile) => (
                  <SuggestionCard
                    key={tile.id}
                    tile={tile}
                    reasoning={tile.meta?.reasoning as string | undefined}
                    isSaved={savedTileIds.has(tile.id)}
                    onSave={handleSaveClick}
                    onViewAlternatives={() => handleViewAlternatives(tile)}
                    onDetailsClick={handleDetailsClick}
                    onOpenStaysSettings={onOpenStaysSettings}
                    variant="compact"
                  />
                ))}
                {stayTiles.length > 6 && (
                  <p className="pt-2 text-xs text-zinc-500 dark:text-zinc-400">
                    +{stayTiles.length - 6} more stays available
                  </p>
                )}
              </>
            ) : (
              <p className="py-2 text-xs text-zinc-500 dark:text-zinc-400">No stays found yet.</p>
            )}
          </div>
        )}

        {/* Flights tiles */}
        {flightsExpanded && (
          <div className="px-6 pb-4 space-y-4">
            {flightTiles.length > 0 ? (
              <>
                {flightTiles.slice(0, 6).map((tile) => (
                  <SuggestionCard
                    key={tile.id}
                    tile={tile}
                    reasoning={tile.meta?.reasoning as string | undefined}
                    isSaved={savedTileIds.has(tile.id)}
                    onSave={handleSaveClick}
                    onViewAlternatives={() => handleViewAlternatives(tile)}
                    onDetailsClick={handleDetailsClick}
                    variant="compact"
                  />
                ))}
                {flightTiles.length > 6 && (
                  <p className="pt-2 text-xs text-zinc-500 dark:text-zinc-400">
                    +{flightTiles.length - 6} more flights available
                  </p>
                )}
              </>
            ) : (
              <p className="py-2 text-xs text-zinc-500 dark:text-zinc-400">No flights found yet.</p>
            )}
          </div>
        )}

        {/* Activities tiles */}
        {isExpanded && (
          <div className="px-6 pb-4 space-y-4">
            {filteredActivityTiles.length > 0 ? (
              <>
                {filteredActivityTiles.slice(0, 6).map((tile) => (
                  <SuggestionCard
                    key={tile.id}
                    tile={tile}
                    reasoning={tile.meta?.reasoning as string | undefined}
                    isSaved={savedTileIds.has(tile.id)}
                    onSave={handleSaveClick}
                    onViewAlternatives={() => handleViewAlternatives(tile)}
                    onDetailsClick={handleDetailsClick}
                    variant="compact"
                  />
                ))}
                {filteredActivityTiles.length > 6 && (
                  <p className="pt-2 text-xs text-zinc-500 dark:text-zinc-400">
                    +{filteredActivityTiles.length - 6} more activities available
                  </p>
                )}
              </>
            ) : (
              <p className="py-2 text-xs text-zinc-500 dark:text-zinc-400">
                No activities found yet.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Details modal */}
      <TileDetailsModal
        tile={selectedTile}
        isOpen={selectedTile !== null}
        isSaved={selectedTile ? savedTileIds.has(selectedTile.id) : false}
        onClose={handleCloseModal}
        onSaveClick={handleSaveClick}
      />

      {/* Alternatives modal (PLANNING mode) */}
      {effectiveMode === 'planning' && (
        <AlternativesModal
          open={alternativesTile !== null}
          onOpenChange={(open) => !open && handleCloseAlternatives()}
          currentTile={alternativesTile}
          alternatives={alternativesTile ? getAlternatives(alternativesTile) : []}
          category={alternativesTile?.type === 'hotel' ? 'Hotel' : alternativesTile?.type === 'flight' ? 'Flight' : 'Activity'}
          onSelect={handleSelectAlternative}
        />
      )}
    </ModalErrorBoundary>
  );
}
