'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * BookingSection
 *
 * The "Itinerary Manifest" - a categorized shopping experience for trip bookables.
 *
 * Layout:
 * - Desktop: 8-column manifest (CategorySections) + 4-column sticky checkout sidebar
 * - Mobile: Stacked layout with floating checkout bar
 *
 * States:
 * - S3 (Book view): Full manifest layout with all categories
 * - S2 with tiles: Preview mode with MiniCards (Plan view)
 * - S2 generating: Skeleton loaders
 * - S2 without tiles: Minimal placeholder
 *
 * Two-Mode System:
 * - PLANNING mode: Shows SuggestionCard with AI reasoning, no checkout
 * - BOOKING mode: Reserved for future price comparison and checkout flow
 *
 * @see docs/ux_unified_architecture.md Section I.B - Booking Suggestions Pattern
 */


import { Lock, Package } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { MiniCardSkeleton } from '@/components/tiles/MiniCard';
import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
interface TileFilters {
  sort: 'recommended' | 'price_low' | 'price_high' | 'rating';
  freeCancel: boolean;
  maxPrice: number | null;
}
import { DS } from '@/lib/design-system';
import { getActiveSpecialists } from '@/lib/specialist-utils';
import { activityMatchesSpecialist as registryMatch } from '@/lib/specialists';
import { getTotalTileCount, isBookableActivityTile, normalizeTileType, selectTilesByType } from '@/lib/tileSelectors';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { GenerationState, PlanViewState, StrategySection, ViewMode } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { PartnerPrice,Tile  } from '@/types/tile';

import { CategorySection } from './booking/CategorySection';
import { CheckoutSidebar } from './booking/CheckoutSidebar';
import { AlternativesModal } from './modals/AlternativesModal';
import { isGenerating } from './planStateHelpers';
import { SuggestionCard } from './tiles/SuggestionCard';

/** Check if an activity tile matches active specialist types (with experience pass-through) */
function activityMatchesSpecialist(tile: Tile, specialistTypes: string[]): boolean {
  if (tile.tags?.includes('experience')) return true;
  return registryMatch(tile, specialistTypes);
}

// Category configuration for manifest layout
const CATEGORY_CONFIG = [
  { key: 'flights', emoji: '✈️', label: 'Flights', types: ['flight'] },
  { key: 'stays', emoji: '🏨', label: 'Stays', types: ['hotel', 'stay', 'accommodation'] },
  { key: 'activities', emoji: '🤿', label: 'Activities', types: ['activity', 'experience', 'tour', 'attraction'] },
] as const;

const EMPTY_SAVED_TILE_IDS = new Set<string>();

interface BookingSectionProps {
  state: PlanViewState;
  tiles: Record<string, Tile> | Tile[];
  generation?: GenerationState | null;
  hasStrategyContent?: boolean;
  /** Set of saved tile IDs (from shortlist) */
  savedTileIds?: Set<string>;
  /** Callback when user clicks Save on a tile */
  onSaveTile?: (tile: Tile) => void;
  /** Callback when user wants to remove a tile from trip */
  onRemoveTile?: (tileId: string) => void;
  /** Callback to open a sheet (for "set trip length" link) */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Callback for checkout action */
  onCheckout?: () => void;
  /** Whether we're in the full Book view (manifest layout) */
  isBookView?: boolean;
  /**
   * Whether trip dates are set.
   * Used to conditionally show "unlock" message.
   * @see docs/ux_unified_architecture.md Section XII
   */
  hasDates?: boolean;
  /**
   * Two-mode system: planning or booking.
   * - planning: Shows SuggestionCard with AI reasoning
   * - booking: Reserved for future price comparison flow
   * @see docs/ux_unified_architecture.md Section I.B
   */
  mode?: ViewMode;
  /** Callback when user wants to view alternatives for a tile */
  onViewAlternatives?: (tile: Tile) => void;
  /** Partner prices for booking mode (keyed by tile ID) */
  partnerPrices?: Record<string, PartnerPrice[]>;
  /** Set of tile IDs in cart (for booking mode) */
  cartTileIds?: Set<string>;
  /** Callback to toggle cart state */
  onCartToggle?: (tile: Tile) => void;
  /** Strategy sections for contextual headers (specialist-aware) */
  strategySections?: StrategySection[];
  /** Callback to open stays/hotel settings sheet (for hotel gear icons) */
  onOpenStaysSettings?: () => void;
  /** Controlled expanded state — when provided, internal toggle is suppressed */
  isExpanded?: boolean;
  /** Callback when expand state should change (only used when isExpanded is provided) */
  onToggleExpanded?: () => void;
  /** Controlled expanded state for flights section */
  flightsExpanded?: boolean;
  /** Callback when flights expand state should change */
  onToggleFlights?: () => void;
}

export function BookingSection({
  state,
  tiles: propTiles,
  generation,

  hasStrategyContent: _hasStrategyContent, // Deprecated: mode is now SSoT, not state
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
  // FIX: Live subscription to tiles - ensures updates even if parent doesn't re-render
  const storeTiles = useDocumentStore(useShallow((s) => s.document?.tiles));
  const tiles = storeTiles ?? propTiles;

  // Auto-collapse in S3 — hotels are already visible as check-in/check-out blocks in the timeline
  const hasItinerary = state === 'S3_ITINERARY_READY' || state === 'S3_EDITING';
  const [internalExpanded] = useState(!hasItinerary);
  const isExpanded = controlledExpanded ?? internalExpanded;
  const [selectedTile, setSelectedTile] = useState<Tile | null>(null);
  const [alternativesTile, setAlternativesTile] = useState<Tile | null>(null);
  const [filters] = useState<TileFilters>({
    sort: 'recommended',
    freeCancel: false,
    maxPrice: null,
  });

  // Determine effective mode based on props
  // If isBookView is explicitly set, use booking mode
  const effectiveMode: ViewMode = isBookView ? 'booking' : mode;

  // Convert tiles to array if needed
  const tileArray = useMemo(() => Array.isArray(tiles) ? tiles : Object.values(tiles), [tiles]);
  const tilesByType = selectTilesByType(tiles);
  const totalTiles = getTotalTileCount(tilesByType);

  // Compute category counts using normalized type matching
  const stayTiles = tileArray.filter(t => normalizeTileType(t.type) === 'hotel');
  const flightTiles = tileArray.filter(t => normalizeTileType(t.type) === 'flight');

  // Get saved tiles for checkout sidebar
  const savedTiles = useMemo(() => {
    return tileArray.filter(t => savedTileIds.has(t.id));
  }, [tileArray, savedTileIds]);

  // Calculate total from saved tiles
  const checkoutTotal = useMemo(() => {
    return savedTiles.reduce((sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0), 0);
  }, [savedTiles]);

  // Extract active specialists for contextual headers
  const activeSpecialists = useMemo(() => {
    return getActiveSpecialists(strategySections);
  }, [strategySections]);

  // Get currency from first saved tile or first tile
  const checkoutCurrency = useMemo(() => {
    const tile = savedTiles[0] || tileArray[0];
    return tile?.currency || 'USD';
  }, [savedTiles, tileArray]);

  // Apply filters and sorting to tiles
  const applyFilters = useCallback((tilesToFilter: Tile[]): Tile[] => {
    let result = [...tilesToFilter];

    // Filter: free cancellation
    if (filters.freeCancel) {
      result = result.filter((t) => t.is_refundable === true);
    }

    // Filter: max price
    if (filters.maxPrice !== null) {
      result = result.filter((t) => {
        const price = t.total_inclusive ?? t.price_estimate;
        return price != null && price <= filters.maxPrice!;
      });
    }

    // Sort
    switch (filters.sort) {
      case 'price_low':
        result.sort((a, b) => {
          const aPrice = a.total_inclusive ?? a.price_estimate ?? Infinity;
          const bPrice = b.total_inclusive ?? b.price_estimate ?? Infinity;
          return aPrice - bPrice;
        });
        break;
      case 'price_high':
        result.sort((a, b) => {
          const aPrice = a.total_inclusive ?? a.price_estimate ?? 0;
          const bPrice = b.total_inclusive ?? b.price_estimate ?? 0;
          return bPrice - aPrice;
        });
        break;
      case 'rating':
        result.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
        break;
      // 'recommended' keeps original order
    }

    return result;
  }, [filters]);

  // Get max price for current category (for filter presets) - hidden for demo
  // const maxPriceInCategory = useMemo(() => {
  //   const categoryTiles = activeCategory === 'stays' ? stayTiles
  //     : activeCategory === 'flights' ? flightTiles
  //     : activityTiles;
  //   const prices = categoryTiles
  //     .map((t) => t.total_inclusive ?? t.price_estimate)
  //     .filter((p): p is number => p != null);
  //   return prices.length > 0 ? Math.max(...prices) : undefined;
  // }, [activeCategory, stayTiles, flightTiles, activityTiles]);

  // Get currency from first tile with price - hidden for demo
  // const currency = useMemo(() => {
  //   const tile = tileArray.find((t) => t.currency);
  //   return tile?.currency === 'EUR' ? '€' : tile?.currency === 'GBP' ? '£' : '$';
  // }, [tileArray]);

  // Handlers for MiniCard actions
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

  // Handler for viewing alternatives
  const handleViewAlternatives = useCallback((tile: Tile) => {
    if (onViewAlternatives) {
      onViewAlternatives(tile);
    } else {
      // Use internal alternatives modal
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

  // Get alternatives for a tile (same category, excluding current)
  const getAlternatives = useCallback((tile: Tile): Tile[] => {
    return tileArray.filter(t =>
      t.id !== tile.id &&
      t.type === tile.type
    );
  }, [tileArray]);

  // Handler for tile click in CategorySection
  const handleTileClick = useCallback((tile: Tile) => {
    setSelectedTile(tile);
  }, []);

  // Handler for removing tile from trip
  const handleRemoveTile = useCallback((tileId: string) => {
    onRemoveTile?.(tileId);
  }, [onRemoveTile]);

  // Group tiles by category for manifest layout (using normalized type matching)
  // Activities are filtered by active specialists when domain specialists are present
  const tilesByCategory = useMemo(() => {
    const grouped: Record<string, Tile[]> = {};
    for (const cat of CATEGORY_CONFIG) {
      const targetType = cat.key === 'stays' ? 'hotel' : cat.key === 'flights' ? 'flight' : 'activity';
      let categoryTiles = tileArray.filter(t => normalizeTileType(t.type) === targetType);

      // Exclude fill-day generated activities from booking manifest
      if (cat.key === 'activities') {
        categoryTiles = categoryTiles.filter(isBookableActivityTile);
      }

      // Filter activities by specialist relevance when domain specialists are active
      if (cat.key === 'activities' && activeSpecialists.length > 0) {
        categoryTiles = categoryTiles.filter(t => activityMatchesSpecialist(t, activeSpecialists));
      }

      grouped[cat.key] = categoryTiles;
    }
    return grouped;
  }, [tileArray, activeSpecialists]);

  // GAP 4 FIX: Hide entire section when no tiles exist
  // This prevents showing an empty tab bar or placeholder noise
  // Specialist cards + map fill the right panel instead
  // NOTE: Must be AFTER all hook declarations to satisfy Rules of Hooks
  if (totalTiles === 0) {
    return null;
  }

  // PLANNING mode: Show S2-style preview regardless of S2/S3 state
  // Mode is the SSoT for UI variant, not state. See docs/ux_unified_architecture.md
  if (effectiveMode === 'planning' && totalTiles > 0 && !isGenerating(generation)) {
    return (
      <ModalErrorBoundary>
        <div id="booking-section">
          <div className="px-6 pt-0 pb-1">
            {savedTileIds.size > 0 && (
              <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full ${DS.textSize.micro} font-medium bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 mt-2`}>
                {savedTileIds.size} in trip
              </span>
            )}
            {/* Section-level lock message - only show if dates are NOT set */}
            {/* @see docs/ux_unified_architecture.md Section XII - Tiles-first logic */}
            {!hasDates && (
              <p className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400 mt-2">
                <Lock className="h-3 w-3" />
                <span>
                  Booking links unlock after you{' '}
                  {onOpenSheet ? (
                    <button
                      type="button"
                      onClick={() => onOpenSheet('dates')}
                      className="text-emerald-600 hover:text-emerald-500 dark:text-emerald-500 dark:hover:text-emerald-400 underline underline-offset-2"
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
                  {applyFilters(stayTiles).slice(0, 6).map((tile) => (
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
                  {applyFilters(stayTiles).length > 6 && (
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 pt-2">
                      +{applyFilters(stayTiles).length - 6} more stays available
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs text-zinc-500 dark:text-zinc-400 py-2">No stays found yet.</p>
              )}
            </div>
          )}

          {/* Flights tiles */}
          {flightsExpanded && (
            <div className="px-6 pb-4 space-y-4">
              {flightTiles.length > 0 ? (
                <>
                  {applyFilters(flightTiles).slice(0, 6).map((tile) => (
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
                  {applyFilters(flightTiles).length > 6 && (
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 pt-2">
                      +{applyFilters(flightTiles).length - 6} more flights available
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs text-zinc-500 dark:text-zinc-400 py-2">No flights found yet.</p>
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

  // S2 generating: skeleton loaders (YC Demo polish)
  if (state.startsWith('S2_') && isGenerating(generation)) {
    const message = totalTiles > 0 ? 'Refreshing deals…' : 'Searching deals…';
    return (
      <div id="booking-section" className="px-4 py-2 space-y-4 animate-in fade-in duration-500">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{message}</p>
        <MiniCardSkeleton />
        <MiniCardSkeleton />
        <MiniCardSkeleton />
      </div>
    );
  }

  // S2 without tiles or without strategy content: minimal placeholder
  if (state.startsWith('S2_')) {
    return (
      <div id="booking-section" className="px-4 py-2">
        <p className="text-xs text-zinc-400 dark:text-zinc-500">
          Booking options appear after itinerary.
        </p>
      </div>
    );
  }

  // BOOKING mode only: Full "Itinerary Manifest" layout with checkout sidebar
  // Mode is the SSoT - state (S3) alone doesn't trigger booking UI
  if (effectiveMode === 'booking') {
    if (totalTiles === 0) {
      return (
        <div id="booking-section" className="flex items-center justify-center h-64">
          <div className="text-center">
            <Package className="w-12 h-12 text-zinc-300 dark:text-zinc-600 mx-auto mb-3" />
            <p className="text-zinc-500 dark:text-zinc-400">No booking options available yet.</p>
            <p className="text-sm text-zinc-400 dark:text-zinc-500 mt-1">
              Generate an itinerary to see bookable options.
            </p>
          </div>
        </div>
      );
    }

    // Manifest layout: Categories + Checkout Sidebar
    return (
      <ModalErrorBoundary>
        <div id="booking-section" className="h-full">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-full p-4 lg:p-6">
            {/* LEFT: Category Manifest (Scrollable) - pb-24 reserves space for mobile checkout footer */}
            <div className="lg:col-span-8 space-y-6 overflow-y-auto custom-scrollbar pb-24 lg:pb-0">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-zinc-900 dark:text-white">Your Trip Options</h2>
                  <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
                    {totalTiles} options found • Add items to your trip
                  </p>
                </div>
                {savedTileIds.size > 0 && (
                  <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
                    {savedTileIds.size} in trip
                  </span>
                )}
              </div>

              {/* Category Sections */}
              {CATEGORY_CONFIG.map((cat) => (
                <CategorySection
                  key={cat.key}
                  emoji={cat.emoji}
                  label={cat.label}
                  items={tilesByCategory[cat.key] || []}
                  savedTileIds={savedTileIds}
                  onSaveTile={onSaveTile}
                  onTileClick={handleTileClick}
                  defaultExpanded={cat.key === 'flights'} // Expand flights by default
                  mode={effectiveMode} // Mode-aware rendering (hearts vs cart)
                />
              ))}
            </div>

            {/* RIGHT: Checkout Sidebar (Sticky on desktop) */}
            <div className="hidden lg:block lg:col-span-4">
              <CheckoutSidebar
                selectedTiles={savedTiles}
                total={checkoutTotal}
                currency={checkoutCurrency}
                onRemoveTile={handleRemoveTile}
                onCheckout={onCheckout}
                checkoutDisabled={savedTiles.length === 0}
                checkoutDisabledReason={savedTiles.length === 0 ? 'Add items to your trip first' : undefined}
              />
            </div>
          </div>

          {/* Mobile: Fixed Checkout Footer */}
          <div className="lg:hidden fixed bottom-0 left-0 right-0 z-30 bg-white/95 dark:bg-zinc-950/95 backdrop-blur-sm border-t border-zinc-200 dark:border-white/10 p-4 pb-[env(safe-area-inset-bottom)] flex items-center justify-between">
            <div className="flex flex-col">
              <span className="text-xs text-zinc-500 dark:text-zinc-400">Est. Total</span>
              <span className="font-bold text-lg">
                {checkoutCurrency === 'USD' ? '$' : checkoutCurrency === 'EUR' ? '€' : checkoutCurrency === 'GBP' ? '£' : checkoutCurrency}
                {checkoutTotal.toLocaleString()}
              </span>
            </div>
            <button
              onClick={onCheckout}
              disabled={savedTiles.length === 0}
              className={cn(
                'px-6 py-3 rounded-lg font-semibold text-sm transition-colors',
                savedTiles.length > 0
                  ? 'bg-emerald-600 text-white hover:bg-emerald-500 shadow-soft'
                  : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-500 cursor-not-allowed'
              )}
            >
              Checkout
            </button>
          </div>
        </div>

        {/* Details modal */}
        <TileDetailsModal
          tile={selectedTile}
          isOpen={selectedTile !== null}
          isSaved={selectedTile ? savedTileIds.has(selectedTile.id) : false}
          onClose={handleCloseModal}
          onSaveClick={handleSaveClick}
        />
      </ModalErrorBoundary>
    );
  }

  // Other states: don't render (no empty padding)
  return null;
}

export default BookingSection;
