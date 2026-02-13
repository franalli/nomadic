/**
 * TripHealthBar
 *
 * Compact horizontal stats bar showing trip status and inventory counts.
 * Displays at top of S2StrategyView as a singleton (General Agent visualization).
 *
 * This replaces the large TripHealthDashboard card - General Agent data is now
 * shown as a compact bar, while Specialists get full AgentCards in the feed below.
 */

'use client';

import { Hotel, MapPin, Plane } from 'lucide-react';
import { useMemo } from 'react';

import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// =============================================================================
// Types
// =============================================================================

interface TripSummary {
  destination: string;
  dates: string;
  travelers: string;
}

interface TripHealthBarProps {
  /** Trip summary from General Agent section */
  tripSummary?: TripSummary;
  /** All tiles for inventory counts */
  tiles: Record<string, Tile>;
  /** Optional className for styling */
  className?: string;
}

// =============================================================================
// Component
// =============================================================================

export function TripHealthBar({ tripSummary, tiles, className }: TripHealthBarProps) {
  // Count tiles by type
  const tileArray = useMemo(() => Object.values(tiles), [tiles]);
  const hotels = tileArray.filter(
    (t) => t.type === 'hotel' || t.type === 'stay' || t.type === 'accommodation'
  ).length;
  const flights = tileArray.filter((t) => t.type === 'flight').length;
  const activities = tileArray.filter(
    (t) => t.type === 'activity' || t.type === 'experience' || t.type === 'tour' || t.type === 'attraction'
  ).length;

  const hasInventory = hotels > 0 || flights > 0 || activities > 0;
  const hasTripInfo = tripSummary?.destination || tripSummary?.dates;

  return (
    <div
      className={cn(
        'flex items-center justify-between px-4 py-2.5 rounded-lg bg-card border border-border',
        className
      )}
    >
      {/* Left: Status indicator + trip info */}
      <div className="flex items-center gap-3">
        {/* Status dot */}
        <div
          className={cn(
            'w-2 h-2 rounded-full flex-shrink-0',
            hasInventory ? 'bg-emerald-500' : 'bg-emerald-500'
          )}
        />

        {/* Status text */}
        <span className="text-sm font-medium text-card-foreground">
          {hasInventory ? 'Ready to customize' : 'Searching options...'}
        </span>

        {/* Trip info (destination + dates) */}
        {hasTripInfo && (
          <span className="text-xs text-muted-foreground hidden sm:inline">
            {tripSummary?.destination}
            {tripSummary?.destination && tripSummary?.dates && ' · '}
            {tripSummary?.dates}
          </span>
        )}
      </div>

      {/* Right: Inventory counts */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5" title="Hotels">
          <Hotel className="w-3.5 h-3.5" />
          <span className="font-medium text-card-foreground">{hotels}</span>
        </span>
        <span className="flex items-center gap-1.5" title="Flights">
          <Plane className="w-3.5 h-3.5" />
          <span className="font-medium text-card-foreground">{flights}</span>
        </span>
        <span className="flex items-center gap-1.5" title="Activities">
          <MapPin className="w-3.5 h-3.5" />
          <span className="font-medium text-card-foreground">{activities}</span>
        </span>
      </div>
    </div>
  );
}

export default TripHealthBar;
