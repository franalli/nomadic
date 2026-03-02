/**
 * Formatting utilities
 *
 * Shared price/currency formatters used across tile cards, modals, and checkout.
 * Pill-specific formatters for header display (dates, travelers, budget).
 */

import type { Tile } from '@/types/tile';

import { parseISODateLocal } from './date-utils';

// Use centralized date parser to avoid timezone issues
const parseDate = parseISODateLocal;

/**
 * Format date range for pill display.
 * Returns null only if BOTH dates are missing (triggers "Add dates" placeholder).
 * Shows just the date if only one is set (no question mark).
 *
 * @example formatDateRangeForPills("2024-12-15", "2024-12-22") → "Dec 15 – 22"
 * @example formatDateRangeForPills("2024-12-28", "2025-01-05") → "Dec 28 – Jan 5"
 * @example formatDateRangeForPills("2024-12-15", null) → "Dec 15"
 * @example formatDateRangeForPills(null, "2024-12-22") → "Dec 22"
 * @example formatDateRangeForPills(null, null) → null
 */
export function formatDateRangeForPills(
  startDate: string | null | undefined,
  endDate: string | null | undefined
): string | null {
  const start = parseDate(startDate);
  const end = parseDate(endDate);

  // No dates at all - return null for "Add dates" placeholder
  if (!start && !end) return null;

  const formatter = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  });

  // Only one date set - show just that date (treat any single date as start)
  if (start && !end) {
    return formatter.format(start);
  }
  if (!start && end) {
    return formatter.format(end);
  }

  // Both dates present
  // Check if same month for compact format
  if (start!.getMonth() === end!.getMonth() && start!.getFullYear() === end!.getFullYear()) {
    // Same month: "Dec 15 – 22"
    const monthDay = formatter.format(start!); // "Dec 15"
    const endDay = end!.getDate().toString();
    return `${monthDay} – ${endDay}`;
  }

  // Different months: "Dec 28 – Jan 5"
  return `${formatter.format(start!)} – ${formatter.format(end!)}`;
}

/**
 * Format travelers count for pill display.
 * Always returns a user-friendly string (never null).
 *
 * @example formatTravelersForPills(1, 0) → "1 adult"
 * @example formatTravelersForPills(2, 0) → "2 adults"
 * @example formatTravelersForPills(2, 1) → "2 adults · 1 child"
 * @example formatTravelersForPills(null, null) → "1 adult"
 */
export function formatTravelersForPills(
  adults: number | null | undefined,
  children: number | null | undefined
): string {
  const a = adults ?? 1; // Default to 1 adult
  const c = children ?? 0;

  const adultText = a === 1 ? '1 adult' : `${a} adults`;
  if (c === 0) return adultText;

  const childText = c === 1 ? '1 child' : `${c} children`;
  return `${adultText} · ${childText}`;
}

/**
 * Format budget for pill display.
 * Returns null if budget is not set (triggers "optional" tone).
 * Guards against invalid currency codes.
 *
 * @example formatBudgetForPills(2000, "USD") → "$2,000"
 * @example formatBudgetForPills(1500, "EUR") → "€1,500"
 * @example formatBudgetForPills(null, "USD") → null
 * @example formatBudgetForPills(2000, "INVALID") → "2,000 INVALID"
 */
export function formatBudgetForPills(
  budget: number | null | undefined,
  currency: string | null | undefined
): string | null {
  if (budget == null) return null;
  const curr = currency ?? 'USD';
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: curr,
      maximumFractionDigits: 0,
    }).format(budget);
  } catch {
    // Fallback for invalid currency codes
    return `${budget.toLocaleString('en-US')} ${curr}`;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Price Formatting — shared across tile cards, modals, and checkout
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format a numeric amount as currency using Intl.NumberFormat.
 * Single source of truth for currency formatting across the app.
 *
 * @example formatPrice(1500) → "$1,500"
 * @example formatPrice(299, "EUR") → "€299"
 * @example formatPrice(0) → "$0"
 */
export function formatPrice(amount: number, currency: string = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

/**
 * Format a Tile's price as a single display string with basis suffix.
 * Used by compact card components (MiniCard, etc.)
 *
 * @example formatTilePrice(hotelTile) → "$250 /night"
 * @example formatTilePrice(flightTile) → "$899 total"
 * @example formatTilePrice(tileWithNoPrice) → ""
 */
export function formatTilePrice(tile: Tile): string {
  const basis = tile.price_basis;
  // For per-unit bases, prefer the per-unit price_estimate over the all-in total
  const price = (basis === 'per_night' || basis === 'per_person')
    ? (tile.price_estimate ?? tile.total_inclusive)
    : (tile.total_inclusive ?? tile.price_estimate);
  if (price == null) return '';

  const formatted = formatPrice(price, tile.currency || 'USD');

  if (basis === 'per_night') return `${formatted} /night`;
  if (basis === 'per_person') return `${formatted} /person`;
  if (basis === 'total' || tile.total_inclusive != null) return `${formatted} total`;

  return formatted;
}

/**
 * Format a Tile's price with both per-unit and optional total breakdown.
 * Used by detail modals that show itemized pricing (TileDetailsModal, etc.)
 *
 * @example formatTilePriceDetailed(hotelTile3Nights) → { perUnit: "$250 /night", total: "$750 total (3 nights)" }
 * @example formatTilePriceDetailed(flightTile) → { perUnit: "$899 total" }
 */
export function formatTilePriceDetailed(tile: Tile): { perUnit: string; total?: string } {
  const basis = tile.price_basis;
  // For per-unit bases, prefer the per-unit price_estimate over the all-in total
  const price = (basis === 'per_night' || basis === 'per_person')
    ? (tile.price_estimate ?? tile.total_inclusive)
    : (tile.total_inclusive ?? tile.price_estimate);
  if (price == null) return { perUnit: '' };

  const currency = tile.currency || 'USD';
  const formatted = formatPrice(price, currency);

  if (basis === 'per_night') {
    const meta = tile.meta as Record<string, unknown> | undefined;
    const nights = typeof meta?.nights === 'number' ? meta.nights : null;
    const totalPrice = tile.total_inclusive ?? (nights ? price * nights : null);
    if (nights && nights > 1 && totalPrice) {
      const total = formatPrice(totalPrice, currency);
      return {
        perUnit: `${formatted} /night`,
        total: `${total} total (${nights} nights)`,
      };
    }
    return { perUnit: `${formatted} /night` };
  }

  if (basis === 'per_person') {
    return { perUnit: `${formatted} /person` };
  }

  if (basis === 'total' || tile.total_inclusive != null) {
    return { perUnit: `${formatted} total` };
  }

  return { perUnit: formatted };
}
