/**
 * SelectionsBar
 *
 * Horizontal carousel showing tiles the user has hearted (preferred).
 * Groups selections by type: Stays (single-select) and Activities (multi-select).
 * Auto-regeneration happens in background - no manual Update button needed.
 *
 * @see docs/ux_unified_architecture.md - Unified Planning View
 */

'use client';

import { Heart, Loader2, X } from 'lucide-react';
import { useMemo } from 'react';

import { activityMatchesSpecialist as registryMatch, getSpecialistConfig } from '@/lib/specialists';
import { cn, isFlightType, isHotelType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

export interface SelectionsBarProps {
  /** Map of all tiles (keyed by ID) */
  tiles: Record<string, Tile>;
  /** Set of preferred tile IDs from documentStore */
  preferredTileIds: Set<string>;
  /** Callback when user removes a preference */
  onRemovePreference: (tileId: string) => void;
  /** Callback when user clicks on a tile (scroll to tile in browser) */
  onTileClick: (tileId: string) => void;
  /** Whether bar is in sticky mode */
  isSticky?: boolean;
  /** Additional className */
  className?: string;
  /** Whether regeneration is in progress (shows spinner) */
  isRegenerating?: boolean;
  /** Active specialist types for filtering (e.g., ['diving', 'local_expert']) */
  activeSpecialistTypes?: string[];
}

/** Tile card component - reused for both groups */
function TileCard({
  tile,
  onTileClick,
  onRemovePreference,
}: {
  tile: Tile;
  onTileClick: (id: string) => void;
  onRemovePreference: (id: string) => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onTileClick(tile.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onTileClick(tile.id);
        }
      }}
      className="flex-shrink-0 snap-start group relative text-left cursor-pointer"
    >
      {/* Thumbnail */}
      <div className="w-20 h-14 rounded-lg overflow-hidden bg-zinc-100 dark:bg-zinc-800 ring-1 ring-zinc-200 dark:ring-white/10">
        {tile.image_url ? (
          <img
            src={tile.image_url}
            alt={tile.title}
            className="w-full h-full object-cover transition-transform group-hover:scale-105"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-zinc-400 dark:text-zinc-600">
            <Heart className="h-4 w-4" />
          </div>
        )}
      </div>

      {/* Title */}
      <span className="block text-[11px] mt-1 truncate w-20 text-zinc-600 dark:text-zinc-300 group-hover:text-zinc-900 dark:group-hover:text-white transition-colors">
        {tile.title}
      </span>

      {/* Remove button - shows on hover */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRemovePreference(tile.id);
        }}
        className={cn(
          'absolute -top-1 -right-1 w-4 h-4 rounded-full',
          'bg-zinc-100 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700',
          'hover:bg-red-600 hover:border-red-600',
          'flex items-center justify-center',
          'opacity-0 group-hover:opacity-100 transition-all duration-150',
          'focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-500'
        )}
        aria-label={`Remove ${tile.title} from selections`}
      >
        <X className="w-2.5 h-2.5 text-zinc-500 dark:text-zinc-400 group-hover:text-white" />
      </button>
    </div>
  );
}

/** Check if activity category matches specialist type (with component-specific pass-throughs) */
function activityMatchesSpecialist(tile: Tile, specialistTypes: string[]): boolean {
  if (isHotelType(tile.type)) return true;
  if (tile.tags?.includes('experience')) return true;
  return registryMatch(tile, specialistTypes);
}

/** Detect which specialist type a tile belongs to */
function detectSpecialistType(tile: Tile, activeSpecialists: string[]): string {
  const category = (tile.type || '').toLowerCase();
  const title = (tile.title || '').toLowerCase();

  for (const specialist of activeSpecialists) {
    const config = getSpecialistConfig(specialist);
    if (!config) continue;
    for (const kw of config.filterKeywords) {
      if (category.includes(kw) || title.includes(kw)) return specialist;
    }
  }
  return 'activities';
}

export function SelectionsBar({
  tiles,
  preferredTileIds,
  onRemovePreference,
  onTileClick,
  isSticky = false,
  className,
  isRegenerating = false,
  activeSpecialistTypes = [],
}: SelectionsBarProps) {
  // Check if we have domain-specific specialists (diving, hiking, etc.)
  const hasDomainSpecialist = activeSpecialistTypes.some(
    s => s.toLowerCase() !== 'local_expert'
  );

  // Filter and group preferred tiles by type and specialist
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { staySelections, flightSelections, activitySelectionsBySpecialist, filteredOutCount: _filteredOutCount, totalCount } = useMemo(() => {
    const stays: Tile[] = [];
    const flights: Tile[] = [];
    const bySpecialist: Record<string, Tile[]> = {};
    let filteredOut = 0;

    for (const id of preferredTileIds) {
      const tile = tiles?.[id];
      if (!tile) continue;

      if (isHotelType(tile.type)) {
        stays.push(tile);
      } else if (isFlightType(tile.type)) {
        flights.push(tile);
      } else {
        // Filter activities by specialist relevance when domain specialists are active
        if (hasDomainSpecialist && !activityMatchesSpecialist(tile, activeSpecialistTypes)) {
          filteredOut++;
          continue;
        }

        // Group by specialist type for display
        const specialistType = detectSpecialistType(tile, activeSpecialistTypes);
        if (!bySpecialist[specialistType]) {
          bySpecialist[specialistType] = [];
        }
        bySpecialist[specialistType].push(tile);
      }
    }

    return {
      staySelections: stays,
      flightSelections: flights,
      activitySelectionsBySpecialist: bySpecialist,
      filteredOutCount: filteredOut,
      totalCount: stays.length + flights.length + Object.values(bySpecialist).flat().length,
    };
  }, [preferredTileIds, tiles, activeSpecialistTypes, hasDomainSpecialist]);

  // Empty state - show hint to heart tiles
  if (totalCount === 0) {
    return (
      <div
        className={cn(
          'flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground',
          'border-b border-border/50',
          className
        )}
      >
        <Heart className="h-4 w-4 text-zinc-500" />
        <span>Heart tiles below to build your trip</span>
      </div>
    );
  }

  // Compact mode - slim one-line badge when 1-2 selections
  if (totalCount <= 2) {
    const allSelections = [
      ...staySelections,
      ...flightSelections,
      ...Object.values(activitySelectionsBySpecialist).flat(),
    ];

    return (
      <div
        className={cn(
          'flex items-center gap-2 px-4 py-2 text-xs text-zinc-500',
          'border-b border-border/50',
          className
        )}
      >
        <Heart className="w-3 h-3 text-emerald-500 fill-emerald-500" />
        <span>
          {totalCount} selection{totalCount !== 1 ? 's' : ''}
        </span>
        {allSelections.slice(0, 2).map((s) => (
          <span
            key={s.id}
            className="text-zinc-400 truncate max-w-[120px]"
            title={s.title}
          >
            · {s.title?.slice(0, 20)}
          </span>
        ))}
        {isRegenerating && (
          <Loader2 className="ml-auto h-3 w-3 animate-spin text-zinc-400" />
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'px-4 py-3 border-b border-border/50 transition-all duration-200',
        isSticky && 'bg-background/95 backdrop-blur-sm shadow-lg',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <Heart className="h-3.5 w-3.5 text-emerald-500 fill-emerald-500" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Your Selections
        </h3>
        <span className="text-xs px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-medium">
          {totalCount}
        </span>

        {/* Auto-updating indicator - shows when regeneration in progress */}
        {isRegenerating && (
          <div className="ml-auto flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-zinc-100 dark:bg-zinc-800/80 text-zinc-600 dark:text-zinc-300">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>Updating...</span>
          </div>
        )}
      </div>

      {/* Grouped selections */}
      <div className="space-y-2">
        {/* Stays group (single-select) */}
        {staySelections.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-zinc-400 dark:text-zinc-500 mb-1.5">
              Stay ({staySelections.length})
            </div>
            <div className="flex gap-2 overflow-x-auto snap-x snap-mandatory pb-1 scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-transparent">
              {staySelections.map((tile) => (
                <TileCard
                  key={tile.id}
                  tile={tile}
                  onTileClick={onTileClick}
                  onRemovePreference={onRemovePreference}
                />
              ))}
            </div>
          </div>
        )}

        {/* Flights group */}
        {flightSelections.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-zinc-400 dark:text-zinc-500 mb-1.5">
              Flights ({flightSelections.length})
            </div>
            <div className="flex gap-2 overflow-x-auto snap-x snap-mandatory pb-1 scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-transparent">
              {flightSelections.map((tile) => (
                <TileCard
                  key={tile.id}
                  tile={tile}
                  onTileClick={onTileClick}
                  onRemovePreference={onRemovePreference}
                />
              ))}
            </div>
          </div>
        )}

        {/* Activities grouped by specialist */}
        {Object.entries(activitySelectionsBySpecialist).map(([specialist, specialistTiles]) => (
          specialistTiles.length > 0 && (
            <div key={specialist}>
              <div className="text-[10px] uppercase tracking-wide text-zinc-400 dark:text-zinc-500 mb-1.5">
                {specialist.charAt(0).toUpperCase() + specialist.slice(1)} ({specialistTiles.length})
              </div>
              <div className="flex gap-2 overflow-x-auto snap-x snap-mandatory pb-1 scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-transparent">
                {specialistTiles.map((tile) => (
                  <TileCard
                    key={tile.id}
                    tile={tile}
                    onTileClick={onTileClick}
                    onRemovePreference={onRemovePreference}
                  />
                ))}
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  );
}

export default SelectionsBar;
