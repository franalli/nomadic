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

import { Check, Circle } from 'lucide-react';
import { useCallback, useState } from 'react';

import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import { trackEvent } from '@/lib/analytics';
import { cn } from '@/lib/utils';
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

  const savedFlights = flightTiles?.filter((t) => savedTileIds.has(t.id)).length ?? 0;
  const savedStays = stayTiles?.filter((t) => savedTileIds.has(t.id)).length ?? 0;
  const savedActivities = activityTiles?.filter((t) => savedTileIds.has(t.id)).length ?? 0;
  const hasTiles = flightTiles.length > 0 || stayTiles.length > 0 || activityTiles.length > 0;

  return (
    <ModalErrorBoundary>
      <div id="booking-section">
        <div className="px-6 pt-0 pb-1">
          {/* @see docs/ux_unified_architecture.md Section XII - Tiles-first logic */}
          {!hasDates && <BookingLockMessage onOpenSheet={onOpenSheet} />}
        </div>

        {/* Booking progress indicator */}
        {hasTiles && (
          <div className="flex items-center gap-3 px-4 py-2 text-xs text-zinc-500 dark:text-white/40">
            <span className={cn('flex items-center gap-1', savedFlights > 0 && 'text-emerald-600 dark:text-emerald-400')}>
              {savedFlights > 0 ? <Check className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
              Flights
            </span>
            <span className="text-zinc-300 dark:text-white/20">{'\u2192'}</span>
            <span className={cn('flex items-center gap-1', savedStays > 0 && 'text-emerald-600 dark:text-emerald-400')}>
              {savedStays > 0 ? <Check className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
              Stays
            </span>
            <span className="text-zinc-300 dark:text-white/20">{'\u2192'}</span>
            <span className={cn('flex items-center gap-1', savedActivities > 0 && 'text-emerald-600 dark:text-emerald-400')}>
              {savedActivities > 0 ? <Check className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
              Activities
            </span>
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
