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
 * - BOOKING mode: Shows BookableCard with price comparison, checkout sidebar
 *
 * @see docs/ux_unified_architecture.md Section I.B - Booking Suggestions Pattern
 */

'use client';

import { ChevronDown, ChevronUp, Lock, Package } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import { MiniCardSkeleton } from '@/components/tiles/MiniCard';
import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { TileFilterBar, type TileFilters } from '@/components/tiles/TileFilterBar';
import { chipActive, chipBase, chipInactive } from '@/lib/chipStyles';
import { getTotalTileCount, selectTilesByType } from '@/lib/tileSelectors';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { GenerationState, PlanViewState, ViewMode } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { AlternativesModal } from './modals/AlternativesModal';
import { SuggestionCard } from './tiles/SuggestionCard';
import { BookableCard, type PartnerPrice } from './tiles/BookableCard';

import { CategorySection } from './booking/CategorySection';
import { CheckoutSidebar } from './booking/CheckoutSidebar';
import { canShowBookingTiles, canShowTilesPreview, isGenerating } from './planStateHelpers';

// Category types for S2 preview
type TileCategory = 'stays' | 'flights' | 'activities';

// Category configuration for manifest layout
const CATEGORY_CONFIG = [
  { key: 'flights', emoji: '✈️', label: 'Flights', types: ['flight'] },
  { key: 'stays', emoji: '🏨', label: 'Stays', types: ['hotel', 'stay', 'accommodation'] },
  { key: 'activities', emoji: '🤿', label: 'Activities', types: ['activity', 'experience', 'tour', 'attraction'] },
] as const;

export interface BookingSectionProps {
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
   * - booking: Shows BookableCard with price comparison
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
}

export function BookingSection({
  state,
  tiles: propTiles,
  generation,
  hasStrategyContent,
  savedTileIds = new Set(),
  onSaveTile,
  onRemoveTile,
  onOpenSheet,
  hasDates = false,
  onCheckout,
  isBookView = false,
  mode = 'planning',
  onViewAlternatives,
  partnerPrices = {},
  cartTileIds = new Set(),
  onCartToggle,
}: BookingSectionProps) {
  // FIX: Live subscription to tiles - ensures updates even if parent doesn't re-render
  const storeTiles = useDocumentStore((s) => s.document?.tiles);
  const tiles = storeTiles ?? propTiles;

  const [isExpanded, setIsExpanded] = useState(true);
  const [activeCategory, setActiveCategory] = useState<TileCategory>('stays');
  const [selectedTile, setSelectedTile] = useState<Tile | null>(null);
  const [alternativesTile, setAlternativesTile] = useState<Tile | null>(null);
  const [filters, setFilters] = useState<TileFilters>({
    sort: 'recommended',
    freeCancel: false,
    maxPrice: null,
  });

  // Determine effective mode based on props
  // If isBookView is explicitly set, use booking mode
  const effectiveMode: ViewMode = isBookView ? 'booking' : mode;

  // Convert tiles to array if needed
  const tileArray = Array.isArray(tiles) ? tiles : Object.values(tiles);
  const tilesByType = selectTilesByType(tiles);
  const totalTiles = getTotalTileCount(tilesByType);

  // Compute category counts
  const stayTiles = tileArray.filter(t => t.type === 'hotel' || t.type === 'stay' || t.type === 'accommodation');
  const flightTiles = tileArray.filter(t => t.type === 'flight');
  const activityTiles = tileArray.filter(t => t.type === 'activity' || t.type === 'experience' || t.type === 'tour' || t.type === 'attraction');

  // Get saved tiles for checkout sidebar
  const savedTiles = useMemo(() => {
    return tileArray.filter(t => savedTileIds.has(t.id));
  }, [tileArray, savedTileIds]);

  // Calculate total from saved tiles
  const checkoutTotal = useMemo(() => {
    return savedTiles.reduce((sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0), 0);
  }, [savedTiles]);

  // Get currency from first saved tile or first tile
  const checkoutCurrency = useMemo(() => {
    const tile = savedTiles[0] || tileArray[0];
    return tile?.currency || 'USD';
  }, [savedTiles, tileArray]);

  const categoryCounts = {
    stays: stayTiles.length,
    flights: flightTiles.length,
    activities: activityTiles.length,
  };

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

  // Get max price for current category (for filter presets)
  const maxPriceInCategory = useMemo(() => {
    const categoryTiles = activeCategory === 'stays' ? stayTiles
      : activeCategory === 'flights' ? flightTiles
      : activityTiles;
    const prices = categoryTiles
      .map((t) => t.total_inclusive ?? t.price_estimate)
      .filter((p): p is number => p != null);
    return prices.length > 0 ? Math.max(...prices) : undefined;
  }, [activeCategory, stayTiles, flightTiles, activityTiles]);

  // Get currency from first tile with price
  const currency = useMemo(() => {
    const tile = tileArray.find((t) => t.currency);
    return tile?.currency === 'EUR' ? '€' : tile?.currency === 'GBP' ? '£' : '$';
  }, [tileArray]);

  // Get filtered tiles for active category (max 6 for S2 preview)
  const getFilteredCategoryTiles = useCallback((category: TileCategory): Tile[] => {
    const baseTiles = category === 'stays' ? stayTiles
      : category === 'flights' ? flightTiles
      : activityTiles;
    return applyFilters(baseTiles).slice(0, 6);
  }, [stayTiles, flightTiles, activityTiles, applyFilters]);

  const previewTiles = getFilteredCategoryTiles(activeCategory);
  const categoryTotalCount = categoryCounts[activeCategory];
  const filteredCount = applyFilters(
    activeCategory === 'stays' ? stayTiles
      : activeCategory === 'flights' ? flightTiles
      : activityTiles
  ).length;
  const remainingCount = Math.max(0, filteredCount - previewTiles.length);

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

  // Group tiles by category for manifest layout
  const tilesByCategory = useMemo(() => {
    const grouped: Record<string, Tile[]> = {};
    for (const cat of CATEGORY_CONFIG) {
      grouped[cat.key] = tileArray.filter(t => (cat.types as readonly string[]).includes(t.type || ''));
    }
    return grouped;
  }, [tileArray]);

  // S2 with tiles + strategy content: "Options to choose from" with MiniCards
  if (canShowTilesPreview(state, totalTiles, generation, hasStrategyContent) && totalTiles > 0) {
    return (
      <>
        <div id="booking-section" className="border-t border-border">
          {/* Header */}
          <div className="px-4 pt-4 pb-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-card-foreground">
                Available Options
              </h3>
              {savedTileIds.size > 0 && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/15 text-emerald-700 dark:text-emerald-400">
                  {savedTileIds.size} in trip
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Compare and select your favorites.
            </p>
            {/* Section-level lock message - only show if dates are NOT set */}
            {/* @see docs/ux_unified_architecture.md Section XII - Tiles-first logic */}
            {!hasDates && (
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground mt-2">
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

          {/* Category chips with counts */}
          <div className="flex gap-2 px-4 py-3">
            {(['stays', 'flights', 'activities'] as const).map((category) => {
              const count = categoryCounts[category];
              const isActive = activeCategory === category;
              const isDisabled = count === 0;

              return (
                <button
                  key={category}
                  onClick={() => {
                    if (!isDisabled) {
                      setActiveCategory(category);
                    }
                  }}
                  disabled={isDisabled}
                  className={cn(
                    chipBase,
                    'font-medium',
                    isActive
                      ? chipActive
                      : isDisabled
                        ? 'bg-muted/30 text-muted-foreground/50 border-border/30 cursor-not-allowed'
                        : chipInactive
                  )}
                >
                  {category.charAt(0).toUpperCase() + category.slice(1)} ({count})
                </button>
              );
            })}
          </div>

          {/* Filter bar */}
          <div className="px-4 pb-2">
            <TileFilterBar
              filters={filters}
              onFiltersChange={setFilters}
              currency={currency}
              maxPriceInSet={maxPriceInCategory}
            />
          </div>

          {/* Expand/collapse toggle */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex w-full items-center justify-between px-4 py-2 text-sm transition-colors hover:bg-muted"
          >
            <span className="text-muted-foreground">
              {isExpanded ? 'Hide' : 'Show'} {filteredCount} {activeCategory}
              {filteredCount !== categoryTotalCount && (
                <span className="text-muted-foreground/70"> (of {categoryTotalCount})</span>
              )}
            </span>
            {isExpanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>

          {/* Tile cards grid - mode-aware rendering */}
          {isExpanded && (
            <div className="px-4 pb-4 space-y-3">
              {previewTiles.length > 0 ? (
                <>
                  {previewTiles.map((tile) => (
                    effectiveMode === 'planning' ? (
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
                    ) : (
                      <BookableCard
                        key={tile.id}
                        tile={tile}
                        partnerPrices={partnerPrices[tile.id]}
                        isInCart={cartTileIds.has(tile.id)}
                        onBook={(t, partner) => {
                          // External booking redirect would happen here
                          console.log('Book', t.id, 'via', partner);
                        }}
                        onCartToggle={onCartToggle}
                        onDetailsClick={handleDetailsClick}
                      />
                    )
                  ))}
                  {remainingCount > 0 && (
                    <p className="text-xs text-muted-foreground pt-2">
                      +{remainingCount} more {activeCategory} available
                    </p>
                  )}
                </>
              ) : filteredCount === 0 && categoryTotalCount > 0 ? (
                <div className="text-xs text-muted-foreground py-2">
                  <p>No {activeCategory} match your filters.</p>
                  <button
                    type="button"
                    onClick={() => setFilters({ sort: 'recommended', freeCancel: false, maxPrice: null })}
                    className="text-emerald-600 hover:text-emerald-500 dark:text-emerald-500 dark:hover:text-emerald-400 mt-1"
                  >
                    Clear filters
                  </button>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground py-2">
                  No {activeCategory} found yet.
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
      </>
    );
  }

  // S2 generating: skeleton loaders (YC Demo polish)
  if (state.startsWith('S2_') && isGenerating(generation)) {
    const message = totalTiles > 0 ? 'Refreshing deals…' : 'Searching deals…';
    return (
      <div id="booking-section" className="px-4 py-2 space-y-3 animate-in fade-in duration-500">
        <p className="text-xs text-muted-foreground">{message}</p>
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
        <p className="text-xs text-muted-foreground/70">
          Booking options appear after itinerary.
        </p>
      </div>
    );
  }

  // S3/Book View: Full "Itinerary Manifest" layout
  if (canShowBookingTiles(state) || isBookView) {
    if (totalTiles === 0) {
      return (
        <div id="booking-section" className="flex items-center justify-center h-64">
          <div className="text-center">
            <Package className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-muted-foreground">No booking options available yet.</p>
            <p className="text-sm text-muted-foreground/70 mt-1">
              Generate an itinerary to see bookable options.
            </p>
          </div>
        </div>
      );
    }

    // Manifest layout: Categories + Checkout Sidebar
    return (
      <>
        <div id="booking-section" className="h-full">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-full p-4 lg:p-6">
            {/* LEFT: Category Manifest (Scrollable) - pb-24 reserves space for mobile checkout footer */}
            <div className="lg:col-span-8 space-y-6 overflow-y-auto custom-scrollbar pb-24 lg:pb-0">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-foreground">Your Trip Options</h2>
                  <p className="text-sm text-muted-foreground mt-1">
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
          <div className="lg:hidden fixed bottom-0 left-0 right-0 z-30 bg-background/95 backdrop-blur-sm border-t border-border p-4 pb-[env(safe-area-inset-bottom)] flex items-center justify-between">
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">Est. Total</span>
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
                  ? 'bg-emerald-600 text-white hover:bg-emerald-500 shadow-lg shadow-emerald-600/20'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
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
      </>
    );
  }

  // Other states: don't render (no empty padding)
  return null;
}

export default BookingSection;
