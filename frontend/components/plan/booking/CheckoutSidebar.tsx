'use client';

import { ArrowRight, CreditCard, ShieldCheck, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { formatPrice } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

interface LineItem {
  label: string;
  amount: number;
  currency: string;
}

interface CheckoutSidebarProps {
  /** Selected tiles for the trip */
  selectedTiles?: Tile[];
  /** Line items to display (computed from selected tiles) */
  lineItems?: LineItem[];
  /** Total estimated cost */
  total: number;
  /** Currency code */
  currency?: string;
  /** Callback to remove a tile */
  onRemoveTile?: (tileId: string) => void;
  /** Callback for checkout action */
  onCheckout?: () => void;
  /** Whether checkout is disabled */
  checkoutDisabled?: boolean;
  /** Message to show when checkout is disabled */
  checkoutDisabledReason?: string;
}

/**
 * CheckoutSidebar
 *
 * Sticky sidebar showing trip summary and running total.
 * "The Money Shot" - where users commit to their trip.
 */
export function CheckoutSidebar({
  selectedTiles = [],
  lineItems,
  total,
  currency = 'USD',
  onRemoveTile,
  onCheckout,
  checkoutDisabled = false,
  checkoutDisabledReason,
}: CheckoutSidebarProps) {
  // Compute line items from selected tiles if not provided
  const computedLineItems = lineItems || (() => {
    const items: LineItem[] = [];

    // Group by type
    const stays = selectedTiles.filter(t => ['hotel', 'stay', 'accommodation'].includes(t.type || ''));
    const flights = selectedTiles.filter(t => t.type === 'flight');
    const activities = selectedTiles.filter(t => ['activity', 'experience', 'tour'].includes(t.type || ''));

    if (flights.length > 0) {
      const flightTotal = flights.reduce((sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0), 0);
      items.push({ label: 'Flights', amount: flightTotal, currency });
    }

    if (stays.length > 0) {
      const stayTotal = stays.reduce((sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0), 0);
      items.push({ label: `Stays (${stays.length})`, amount: stayTotal, currency });
    }

    if (activities.length > 0) {
      const activityTotal = activities.reduce((sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0), 0);
      items.push({ label: 'Activities', amount: activityTotal, currency });
    }

    return items;
  })();

  return (
    <div className="sticky top-4 space-y-4">
      {/* Main card */}
      <div className="bg-card border rounded-xl p-6 shadow-sm">
        <h3 className="font-semibold text-lg mb-4">Trip Summary</h3>

        {/* Selected items list (if any) */}
        {selectedTiles.length > 0 && (
          <div className="space-y-2 mb-4 pb-4 border-b">
            {selectedTiles.slice(0, 4).map((tile) => (
              <div key={tile.id} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate text-muted-foreground">{tile.title}</span>
                <button
                  type="button"
                  onClick={() => onRemoveTile?.(tile.id)}
                  className="flex-shrink-0 p-1 hover:bg-muted rounded transition-colors"
                >
                  <X className="w-3 h-3 text-muted-foreground" />
                </button>
              </div>
            ))}
            {selectedTiles.length > 4 && (
              <p className="text-xs text-muted-foreground">
                +{selectedTiles.length - 4} more items
              </p>
            )}
          </div>
        )}

        {/* Line items */}
        <div className="space-y-3 mb-6 border-b pb-6">
          {computedLineItems.length > 0 ? (
            computedLineItems.map((item, idx) => (
              <div key={idx} className="flex justify-between text-sm">
                <span className="text-muted-foreground">{item.label}</span>
                <span>{formatPrice(item.amount, currency)}</span>
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground text-center py-2">
              No items selected yet
            </p>
          )}
        </div>

        {/* Total */}
        <div className="flex justify-between items-end mb-6">
          <span className="font-bold text-lg">Total Est.</span>
          <span className="font-bold text-3xl tracking-tight">
            {formatPrice(total, currency)}
          </span>
        </div>

        {/* CTA Button */}
        <Button
          onClick={onCheckout}
          disabled={checkoutDisabled || total === 0}
          className={cn(
            'w-full h-12 text-base font-semibold gap-2',
            !checkoutDisabled && total > 0 && 'shadow-lg shadow-primary/20'
          )}
        >
          Continue to Booking
          <ArrowRight className="w-4 h-4" />
        </Button>

        {/* Disabled reason */}
        {checkoutDisabled && checkoutDisabledReason && (
          <p className="mt-2 text-xs text-muted-foreground text-center">
            {checkoutDisabledReason}
          </p>
        )}

        {/* Security badge */}
        <div className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <ShieldCheck className="w-3 h-3 text-emerald-500" />
          <span>Secure checkout via Stripe</span>
        </div>
      </div>

      {/* Trust badge */}
      <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 flex gap-3 items-start">
        <div className="p-2 bg-emerald-500/20 rounded-full text-emerald-600">
          <CreditCard className="w-4 h-4" />
        </div>
        <div>
          <h4 className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
            No Payment Yet
          </h4>
          <p className="text-xs text-emerald-600/80 dark:text-emerald-400/70 mt-1">
            You won&apos;t be charged until you confirm availability on the next step.
          </p>
        </div>
      </div>
    </div>
  );
}

export default CheckoutSidebar;
