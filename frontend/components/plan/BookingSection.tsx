'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */

import { useMemo, useState } from 'react';

import { MiniCardSkeleton } from '@/components/tiles/MiniCard';
import { getTotalTileCount, normalizeTileType, selectTilesByType } from '@/lib/tileSelectors';
import type { GenerationState, PlanViewState, StrategySection, ViewMode } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { PartnerPrice, Tile } from '@/types/tile';

import { BookingPlanningView } from './BookingPlanningView';
import {
  applyTileFilters,
  buildTilesByCategory,
  DEFAULT_TILE_FILTERS,
  EMPTY_SAVED_TILE_IDS,
  getActiveBookingSpecialists,
  getCheckoutState,
} from './BookingSection.helpers';
import { BookingSectionBookingView } from './BookingSectionBookingView';
import { isEditing, isGenerating, isItineraryReady } from './planStateHelpers';

interface BookingSectionProps {
  state: PlanViewState;
  tiles: Record<string, Tile> | Tile[];
  generation?: GenerationState | null;
  hasStrategyContent?: boolean;
  savedTileIds?: Set<string>;
  onSaveTile?: (tile: Tile) => void;
  onRemoveTile?: (tileId: string) => void;
  onOpenSheet?: (sheet: SheetType) => void;
  onCheckout?: () => void;
  isBookView?: boolean;
  hasDates?: boolean;
  mode?: ViewMode;
  onViewAlternatives?: (tile: Tile) => void;
  partnerPrices?: Record<string, PartnerPrice[]>;
  cartTileIds?: Set<string>;
  onCartToggle?: (tile: Tile) => void;
  strategySections?: StrategySection[];
  onOpenStaysSettings?: () => void;
  isExpanded?: boolean;
  onToggleExpanded?: () => void;
  flightsExpanded?: boolean;
  onToggleFlights?: () => void;
}

export function BookingSection({
  state,
  tiles,
  generation,
  hasStrategyContent: _hasStrategyContent,
  savedTileIds = EMPTY_SAVED_TILE_IDS,
  onSaveTile,
  onRemoveTile,
  onOpenSheet,
  hasDates = false,
  onCheckout,
  isBookView = false,
  mode = 'planning',
  onViewAlternatives,
  partnerPrices: _partnerPrices = {},
  cartTileIds: _cartTileIds = new Set(),
  onCartToggle: _onCartToggle,
  strategySections,
  onOpenStaysSettings,
  isExpanded: controlledExpanded,
  onToggleExpanded: _onToggleExpanded,
  flightsExpanded = false,
  onToggleFlights: _onToggleFlights,
}: BookingSectionProps) {
  const hasItinerary = isItineraryReady(state) || isEditing(state);
  const [internalExpanded] = useState(!hasItinerary);
  const isExpanded = controlledExpanded ?? internalExpanded;
  const effectiveMode: ViewMode = isBookView ? 'booking' : mode;
  const tileArray = useMemo(() => (Array.isArray(tiles) ? tiles : Object.values(tiles)), [tiles]);
  const totalTiles = getTotalTileCount(selectTilesByType(tiles));
  const activeSpecialists = useMemo(
    () => getActiveBookingSpecialists(strategySections),
    [strategySections]
  );
  const tilesByCategory = useMemo(
    () => buildTilesByCategory(tileArray, activeSpecialists),
    [activeSpecialists, tileArray]
  );
  const filteredStayTiles = useMemo(
    () => applyTileFilters(
      DEFAULT_TILE_FILTERS,
      tileArray.filter((tile) => normalizeTileType(tile.type) === 'hotel')
    ),
    [tileArray]
  );
  const filteredFlightTiles = useMemo(
    () => applyTileFilters(
      DEFAULT_TILE_FILTERS,
      tileArray.filter((tile) => normalizeTileType(tile.type) === 'flight')
    ),
    [tileArray]
  );
  const filteredActivityTiles = useMemo(
    () => applyTileFilters(DEFAULT_TILE_FILTERS, tilesByCategory.activities ?? []),
    [tilesByCategory]
  );
  const checkoutState = useMemo(
    () => getCheckoutState(tileArray, savedTileIds),
    [savedTileIds, tileArray]
  );

  if (effectiveMode === 'planning' && totalTiles > 0) {
    return (
      <BookingPlanningView
        filteredStayTiles={filteredStayTiles}
        filteredFlightTiles={filteredFlightTiles}
        filteredActivityTiles={filteredActivityTiles}
        tileArray={tileArray}
        savedTileIds={savedTileIds}
        isExpanded={isExpanded}
        flightsExpanded={flightsExpanded}
        hasDates={hasDates}
        effectiveMode={effectiveMode}
        onSaveTile={onSaveTile}
        onOpenSheet={onOpenSheet}
        onViewAlternatives={onViewAlternatives}
        onOpenStaysSettings={onOpenStaysSettings}
      />
    );
  }

  if (state.startsWith('S2_') && isGenerating(generation)) {
    return (
      <div id="booking-section" className="space-y-4 animate-in fade-in px-4 py-2 duration-500">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {totalTiles > 0 ? 'Refreshing deals…' : 'Searching deals…'}
        </p>
        <MiniCardSkeleton />
        <MiniCardSkeleton />
        <MiniCardSkeleton />
      </div>
    );
  }

  if (state.startsWith('S2_')) {
    return (
      <div id="booking-section" className="px-4 py-2">
        <p className="text-xs text-zinc-500/80 dark:text-zinc-400/80">
          Booking options appear after itinerary.
        </p>
      </div>
    );
  }

  if (effectiveMode === 'booking') {
    return (
      <BookingSectionBookingView
        totalTiles={totalTiles}
        tilesByCategory={tilesByCategory}
        savedTileIds={savedTileIds}
        savedTiles={checkoutState.savedTiles}
        checkoutCurrency={checkoutState.checkoutCurrency}
        checkoutTotal={checkoutState.checkoutTotal}
        hasMixedCheckoutCurrencies={checkoutState.hasMixedCheckoutCurrencies}
        hasUnknownCheckoutCurrency={checkoutState.hasUnknownCheckoutCurrency}
        hasCheckoutCurrencyIssue={checkoutState.hasCheckoutCurrencyIssue}
        onSaveTile={onSaveTile}
        onRemoveTile={onRemoveTile}
        onCheckout={onCheckout}
      />
    );
  }

  return null;
}

export default BookingSection;
