'use client';

import { Layers, Package } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { CategorySection } from './booking/CategorySection';
import { CheckoutSidebar } from './booking/CheckoutSidebar';
import { CATEGORY_CONFIG } from './BookingSection.helpers';

interface BookingSectionBookingViewProps {
  totalTiles: number;
  tilesByCategory: Record<(typeof CATEGORY_CONFIG)[number]['key'], Tile[]>;
  savedTileIds: Set<string>;
  savedTiles: Tile[];
  checkoutCurrency: string;
  checkoutTotal: number;
  hasMixedCheckoutCurrencies: boolean;
  hasUnknownCheckoutCurrency: boolean;
  hasCheckoutCurrencyIssue: boolean;
  onSaveTile?: (tile: Tile) => void;
  onRemoveTile?: (tileId: string) => void;
  onCheckout?: () => void;
}

export function BookingSectionBookingView({
  totalTiles,
  tilesByCategory,
  savedTileIds,
  savedTiles,
  checkoutCurrency,
  checkoutTotal,
  hasMixedCheckoutCurrencies,
  hasUnknownCheckoutCurrency,
  hasCheckoutCurrencyIssue,
  onSaveTile,
  onRemoveTile,
  onCheckout,
}: BookingSectionBookingViewProps) {
  const [selectedTile, setSelectedTile] = useState<Tile | null>(null);
  const [showAll, setShowAll] = useState(false);
  const handleCloseModal = useCallback(() => setSelectedTile(null), []);
  const handleTileClick = useCallback((tile: Tile) => setSelectedTile(tile), []);

  // Track which categories are fully saved for auto-advance
  // (must be above early return to satisfy rules of hooks)
  const completedCategories = useMemo(() => {
    const result = new Set<string>();
    for (const cat of CATEGORY_CONFIG) {
      const catTiles = tilesByCategory[cat.key] ?? [];
      if (catTiles.length > 0 && catTiles.every((t) => savedTileIds.has(t.id))) {
        result.add(cat.key);
      }
    }
    return result;
  }, [tilesByCategory, savedTileIds]);

  if (totalTiles === 0) {
    return (
      <div id="booking-section" className="flex h-64 items-center justify-center">
        <div className="text-center">
          <Package className="mx-auto mb-3 h-12 w-12 text-zinc-400 dark:text-zinc-500" />
          <p className="text-zinc-500 dark:text-zinc-400">No booking options available yet.</p>
          <p className="mt-1 text-sm text-zinc-500/80 dark:text-zinc-400/80">
            Generate an itinerary to see bookable options.
          </p>
        </div>
      </div>
    );
  }

  const checkoutDisabled = savedTiles.length === 0 || hasCheckoutCurrencyIssue || !onCheckout;
  const checkoutDisabledReason =
    savedTiles.length === 0
      ? 'Add items to your trip first'
      : hasMixedCheckoutCurrencies
        ? 'Checkout supports one currency at a time'
        : hasUnknownCheckoutCurrency
          ? 'Some selections are missing currency'
          : !onCheckout
            ? 'Checkout is unavailable right now'
            : undefined;

  return (
    <ModalErrorBoundary>
      <div id="booking-section" className="h-full">
        <div className="grid h-full grid-cols-1 gap-6 p-4 lg:grid-cols-12 lg:p-6">
          <div className="space-y-6 overflow-y-auto pb-24 lg:col-span-8 lg:pb-0">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold text-zinc-900 dark:text-white">
                  Your Trip Options
                </h2>
                <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                  {totalTiles} options found • Add items to your trip
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowAll((prev) => !prev)}
                className={cn(
                  'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                  showAll
                    ? 'bg-zinc-900 text-white dark:bg-white/20 dark:text-white'
                    : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-white/5 dark:text-zinc-400 dark:hover:bg-white/10'
                )}
              >
                <Layers className="h-3.5 w-3.5" />
                {showAll ? 'Categorized' : 'See all'}
              </button>
            </div>

            {CATEGORY_CONFIG.map((category, idx) => {
              const isCompleted = completedCategories.has(category.key);
              const allPriorComplete = CATEGORY_CONFIG.slice(0, idx).every((c) =>
                completedCategories.has(c.key)
              );
              // Auto-expand: first non-completed category where all prior are complete
              const isFirstIncomplete = !isCompleted && allPriorComplete;
              // Auto-collapse completed categories; expand the next incomplete one
              const forceExpanded = showAll
                ? true
                : isCompleted
                  ? false
                  : isFirstIncomplete
                    ? true
                    : undefined;

              return (
                <CategorySection
                  key={category.key}
                  emoji={category.emoji}
                  label={category.label}
                  cta={category.cta}
                  items={tilesByCategory[category.key] ?? []}
                  savedTileIds={savedTileIds}
                  onSaveTile={onSaveTile}
                  onTileClick={handleTileClick}
                  defaultExpanded={category.key === 'flights'}
                  forceExpanded={forceExpanded}
                  mode="booking"
                  collapsible={!showAll}
                />
              );
            })}
          </div>

          <div className="hidden lg:col-span-4 lg:block">
            <CheckoutSidebar
              selectedTiles={savedTiles}
              total={checkoutTotal}
              currency={checkoutCurrency}
              onRemoveTile={onRemoveTile}
              onCheckout={onCheckout}
              checkoutDisabled={checkoutDisabled}
              checkoutDisabledReason={checkoutDisabledReason}
            />
          </div>
        </div>

        <div className="fixed bottom-0 left-0 right-0 z-20 flex items-center justify-between border-t border-zinc-200 bg-white/95 p-4 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm dark:border-white/10 dark:bg-zinc-950/95 lg:hidden">
          <div className="flex flex-col">
            <span className="text-xs text-zinc-500 dark:text-zinc-400">Est. Total</span>
            <span className="text-lg font-bold text-zinc-900 dark:text-white">
              {hasMixedCheckoutCurrencies ? (
                'Multiple currencies'
              ) : hasUnknownCheckoutCurrency ? (
                'Currency unavailable'
              ) : (
                <>
                  {checkoutCurrency === 'USD'
                    ? '$'
                    : checkoutCurrency === 'EUR'
                      ? '€'
                      : checkoutCurrency === 'GBP'
                        ? '£'
                        : checkoutCurrency}
                  {checkoutTotal.toLocaleString()}
                </>
              )}
            </span>
          </div>
          <button
            onClick={onCheckout}
            disabled={checkoutDisabled}
            className={cn(
              'rounded-lg px-6 py-3 text-sm font-semibold transition-colors disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
              !checkoutDisabled
                ? 'bg-zinc-900 text-white shadow-sm hover:bg-zinc-800 dark:bg-emerald-600 dark:hover:bg-emerald-500'
                : 'bg-zinc-100 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-400'
            )}
          >
            Checkout
          </button>
        </div>
      </div>

      <TileDetailsModal
        tile={selectedTile}
        isOpen={selectedTile !== null}
        isSaved={selectedTile ? savedTileIds.has(selectedTile.id) : false}
        onClose={handleCloseModal}
        onSaveClick={onSaveTile}
      />
    </ModalErrorBoundary>
  );
}
