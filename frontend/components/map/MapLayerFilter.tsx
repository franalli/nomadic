/**
 * MapLayerFilter
 *
 * Horizontal pill row for toggling visibility of different activity types on the map.
 * Positioned at the top-left of the map container.
 *
 * @see docs/ux_unified_architecture.md for map-itinerary sync specification
 */

'use client';

import type { LucideIcon } from 'lucide-react';
import { Bed, Bike, Binoculars, Landmark, MapPin, Mountain, Plane, Sailboat, Snowflake, Utensils, Waves } from 'lucide-react';

import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

interface MapLayerFilterProps {
  /** Set of currently visible layer types */
  visibleLayers: Set<string>;
  /** Toggle a layer's visibility */
  onToggle: (layerType: string) => void;
  /** Available layer types (derived from actual items) */
  availableTypes: string[];
  /** Show "All" toggle button */
  showAllButton?: boolean;
  /** Callback to show all layers */
  onShowAll?: () => void;
  className?: string;
}

// =============================================================================
// Layer Config
// =============================================================================

interface LayerConfig {
  icon: LucideIcon;
  label: string;
  activeColor: string;
}

const LAYER_CONFIG: Record<string, LayerConfig> = {
  diving: {
    icon: Waves,
    label: 'Diving',
    activeColor: 'bg-cyan-500 text-white border-cyan-500',
  },
  hiking: {
    icon: Mountain,
    label: 'Hiking',
    activeColor: 'bg-green-500 text-white border-green-500',
  },
  skiing: {
    icon: Snowflake,
    label: 'Skiing',
    activeColor: 'bg-blue-500 text-white border-blue-500',
  },
  cycling: {
    icon: Bike,
    label: 'Cycling',
    activeColor: 'bg-lime-500 text-white border-lime-500',
  },
  surfing: {
    icon: Waves,
    label: 'Surfing',
    activeColor: 'bg-indigo-500 text-white border-indigo-500',
  },
  climbing: {
    icon: Mountain,
    label: 'Climbing',
    activeColor: 'bg-orange-500 text-white border-orange-500',
  },
  sailing: {
    icon: Sailboat,
    label: 'Sailing',
    activeColor: 'bg-cyan-500 text-white border-cyan-500',
  },
  wildlife_safari: {
    icon: Binoculars,
    label: 'Safari',
    activeColor: 'bg-amber-500 text-white border-amber-500',
  },
  hotel: {
    icon: Bed,
    label: 'Hotels',
    activeColor: 'bg-purple-500 text-white border-purple-500',
  },
  flight: {
    icon: Plane,
    label: 'Flights',
    activeColor: 'bg-blue-500 text-white border-blue-500',
  },
  temple: {
    icon: Landmark,
    label: 'Culture',
    activeColor: 'bg-rose-500 text-white border-rose-500',
  },
  food: {
    icon: Utensils,
    label: 'Food',
    activeColor: 'bg-pink-500 text-white border-pink-500',
  },
  local: {
    icon: MapPin,
    label: 'Local',
    activeColor: 'bg-emerald-500 text-white border-emerald-500',
  },
  activity: {
    icon: MapPin,
    label: 'Activities',
    activeColor: 'bg-zinc-500 text-white border-zinc-500',
  },
};

// =============================================================================
// Component
// =============================================================================

export function MapLayerFilter({
  visibleLayers,
  onToggle,
  availableTypes,
  showAllButton = true,
  onShowAll,
  className,
}: MapLayerFilterProps) {
  // Don't render if no types available
  if (availableTypes.length === 0) return null;

  // Check if all layers are visible
  const allVisible = availableTypes.every((type) => visibleLayers.has(type));

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 p-1.5 rounded-lg backdrop-blur-md',
        'bg-black/40 border border-white/10',
        className
      )}
    >
      {/* All button */}
      {showAllButton && (
        <button
          type="button"
          onClick={onShowAll}
          className={cn(
            'px-2.5 py-1.5 rounded-md text-[10px] font-semibold uppercase tracking-wide',
            'transition-all duration-200 border',
            allVisible
              ? 'bg-white text-zinc-900 border-white'
              : 'bg-transparent text-white/70 border-white/20 hover:bg-white/10 hover:text-white'
          )}
        >
          All
        </button>
      )}

      {/* Individual layer toggles */}
      {availableTypes.map((type) => {
        const config = LAYER_CONFIG[type] || {
          icon: MapPin,
          label: type.charAt(0).toUpperCase() + type.slice(1),
          activeColor: 'bg-zinc-500 text-white border-zinc-500',
        };
        const Icon = config.icon;
        const isActive = visibleLayers.has(type);

        return (
          <button
            key={type}
            type="button"
            onClick={() => onToggle(type)}
            className={cn(
              'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] font-semibold uppercase tracking-wide',
              'transition-all duration-200 border',
              isActive
                ? config.activeColor
                : 'bg-transparent text-white/50 border-white/10 hover:bg-white/5 hover:text-white/70'
            )}
          >
            <Icon className="w-3 h-3" />
            <span className="hidden sm:inline">{config.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Compact variant for mobile - just icons
 */
export function MapLayerFilterCompact({
  visibleLayers,
  onToggle,
  availableTypes,
  className,
}: Omit<MapLayerFilterProps, 'showAllButton' | 'onShowAll'>) {
  if (availableTypes.length === 0) return null;

  return (
    <div
      className={cn(
        'flex items-center gap-1 p-1 rounded-lg backdrop-blur-md',
        'bg-black/40 border border-white/10',
        className
      )}
    >
      {availableTypes.map((type) => {
        const config = LAYER_CONFIG[type] || { icon: MapPin, activeColor: 'bg-zinc-500' };
        const Icon = config.icon;
        const isActive = visibleLayers.has(type);

        return (
          <button
            key={type}
            type="button"
            onClick={() => onToggle(type)}
            className={cn(
              'p-1.5 rounded-md transition-all duration-200',
              isActive
                ? `${config.activeColor.split(' ')[0]} text-white`
                : 'bg-transparent text-white/40 hover:bg-white/10 hover:text-white/60'
            )}
          >
            <Icon className="w-4 h-4" />
          </button>
        );
      })}
    </div>
  );
}

export default MapLayerFilter;
