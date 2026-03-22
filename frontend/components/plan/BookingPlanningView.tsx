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

import { useCallback, useState } from 'react';

import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import { trackEvent } from '@/lib/analytics';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { ViewMode } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { BookingLockMessage, BookingSectionGroup } from './BookingPlanningViewParts';
import { AlternativesModal } from './modals/AlternativesModal';

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
  /** Whether stays section is expanded */
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
  const activitiesExpanded = usePanelToggleStore((state) => state.activitiesExpanded);

  const handleDetailsClick = useCallback((tile: Tile) => {
    setSelectedTile(tile);
    const eventType = tile.type === 'hotel' ? 'hotel_clicked' : tile.type === 'flight' ? 'flight_clicked' : 'activity_clicked';
    trackEvent(eventType, null, { tile_type: tile.type, tile_id: tile.id });
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
  const activityTiles = filteredActivityTiles;

  return (
    <ModalErrorBoundary>
      <div id="booking-section">
        <div className="px-6 pt-0 pb-1">
          {/* @see docs/ux_unified_architecture.md Section XII - Tiles-first logic */}
          {!hasDates && <BookingLockMessage onOpenSheet={onOpenSheet} />}
        </div>

        {/* Stays tiles */}
        {isExpanded && (
          <div className="px-6 pb-4">
            <BookingSectionGroup
              title="Stays"
              tiles={stayTiles}
              emptyMessage="No stays found yet."
              savedTileIds={savedTileIds}
              onSave={handleSaveClick}
              onDetailsClick={handleDetailsClick}
              onViewAlternatives={handleViewAlternatives}
              onOpenStaysSettings={onOpenStaysSettings}
            />
          </div>
        )}

        {/* Flights tiles */}
        {flightsExpanded && (
          <div className="px-6 pb-4">
            <BookingSectionGroup
              title="Flights"
              tiles={flightTiles}
              emptyMessage="No flights found yet."
              savedTileIds={savedTileIds}
              onSave={handleSaveClick}
              onDetailsClick={handleDetailsClick}
            />
          </div>
        )}

        {/* Activities tiles */}
        {activitiesExpanded && (
          <div className="px-6 pb-4">
            <BookingSectionGroup
              title="Activities"
              tiles={activityTiles}
              emptyMessage="No activities found yet."
              savedTileIds={savedTileIds}
              onSave={handleSaveClick}
              onDetailsClick={handleDetailsClick}
              onViewAlternatives={handleViewAlternatives}
            />
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
