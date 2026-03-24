'use client';

import { getActiveSpecialists } from '@/lib/specialist-utils';
import { activityMatchesSpecialist as registryMatch } from '@/lib/specialists';
import { isBookableActivityTile, normalizeTileType } from '@/lib/tileSelectors';
import type { StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

export interface TileFilters {
  sort: 'recommended' | 'price_low' | 'price_high' | 'rating';
  freeCancel: boolean;
  maxPrice: number | null;
}

export const DEFAULT_TILE_FILTERS: TileFilters = {
  sort: 'recommended',
  freeCancel: false,
  maxPrice: null,
};

export const CATEGORY_CONFIG = [
  { key: 'flights', emoji: '✈️', label: 'Flights', cta: 'Lock in your flights first — prices change daily' },
  { key: 'stays', emoji: '🏨', label: 'Stays', cta: 'Pick a base for your trip' },
  { key: 'activities', emoji: '🤿', label: 'Activities', cta: 'Fill your days' },
] as const;

export const EMPTY_SAVED_TILE_IDS = new Set<string>();

function activityMatchesSpecialist(tile: Tile, specialistTypes: string[]): boolean {
  if (tile.tags?.includes('experience')) return true;
  return registryMatch(tile, specialistTypes);
}

export function applyTileFilters(filters: TileFilters, tiles: Tile[]): Tile[] {
  let result = [...tiles];

  if (filters.freeCancel) {
    result = result.filter((tile) => tile.is_refundable === true);
  }

  const maxPrice = filters.maxPrice;
  if (maxPrice !== null) {
    result = result.filter((tile) => {
      const price = tile.total_inclusive ?? tile.price_estimate;
      return price != null && price <= maxPrice;
    });
  }

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
    default:
      break;
  }

  return result;
}

export function getActiveBookingSpecialists(strategySections?: StrategySection[]): string[] {
  return getActiveSpecialists(strategySections);
}

export function buildTilesByCategory(
  tileArray: Tile[],
  activeSpecialists: string[]
): Record<(typeof CATEGORY_CONFIG)[number]['key'], Tile[]> {
  return {
    flights: tileArray.filter((tile) => normalizeTileType(tile.type) === 'flight'),
    stays: tileArray.filter((tile) => normalizeTileType(tile.type) === 'hotel'),
    activities: tileArray
      .filter((tile) => normalizeTileType(tile.type) === 'activity')
      .filter(isBookableActivityTile)
      .filter((tile) =>
        activeSpecialists.length === 0 || activityMatchesSpecialist(tile, activeSpecialists)
      ),
  };
}

export function getCheckoutState(tileArray: Tile[], savedTileIds: Set<string>) {
  const savedTiles = tileArray.filter((tile) => savedTileIds.has(tile.id));
  const checkoutCurrencyCodes = savedTiles.map((tile) => tile.currency?.trim().toUpperCase() ?? '');
  const hasUnknownCheckoutCurrency = checkoutCurrencyCodes.some((currency) => currency.length === 0);
  const checkoutCurrencies = new Set(
    checkoutCurrencyCodes.filter((currency) => currency.length > 0)
  );
  const hasMixedCheckoutCurrencies = checkoutCurrencies.size > 1;
  const hasCheckoutCurrencyIssue = hasMixedCheckoutCurrencies || hasUnknownCheckoutCurrency;
  const firstKnownSavedCurrency = checkoutCurrencyCodes.find((currency) => currency.length > 0);
  const fallbackCurrency = tileArray[0]?.currency?.trim().toUpperCase();
  const checkoutCurrency =
    firstKnownSavedCurrency ||
    (fallbackCurrency && fallbackCurrency.length > 0 ? fallbackCurrency : 'USD');
  const checkoutTotal = hasCheckoutCurrencyIssue
    ? 0
    : savedTiles.reduce((sum, tile) => {
        const tileCurrency = tile.currency?.trim().toUpperCase();
        if (!tileCurrency || tileCurrency !== checkoutCurrency) return sum;
        return sum + (tile.total_inclusive ?? tile.price_estimate ?? 0);
      }, 0);

  return {
    savedTiles,
    checkoutCurrency,
    checkoutTotal,
    hasMixedCheckoutCurrencies,
    hasUnknownCheckoutCurrency,
    hasCheckoutCurrencyIssue,
  };
}
