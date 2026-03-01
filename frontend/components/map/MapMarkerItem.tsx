'use client';

/**
 * MapMarkerItem — Per-marker component for InteractiveMap.
 *
 * Includes pin config (icon + color lookup by activity/specialist type),
 * coordinate helpers, and the isolated marker with tooltip.
 *
 * Each instance subscribes to a boolean selector so only the 2 affected markers
 * re-render on hover instead of the entire marker list.
 */

import {
  Anchor, Bed, Bike, Binoculars, Camera, Church, Compass, Dumbbell,
  Flower2, Landmark, type LucideIcon,
  MapPin, Mountain, Music, Palmtree, Plane, Search, ShoppingBag, Snowflake, Star,
  Sunset, Utensils, Waves, Wind,
} from 'lucide-react';
import { memo } from 'react';
import { Marker } from 'react-map-gl/mapbox';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/state/uiStore';

// =============================================================================
// Types
// =============================================================================

export interface MapItem {
  id: string;
  title: string;
  type: string;
  coordinates: { lat: number; lng: number };
  dayNumber?: number;
  period?: 'morning' | 'afternoon' | 'evening';
  source?: 'itinerary' | 'specialist' | 'browse';
  intensity?: 'light' | 'moderate' | 'challenging';
  duration?: string;
  rating?: number;
  reviewCount?: number;
  priceLevel?: number;
}

export interface MapCenter {
  lat: number;
  lng: number;
  zoom: number;
}

// =============================================================================
// Pin Config — exact-key lookup (no fragile string matching)
// =============================================================================

interface PinConfig {
  icon: LucideIcon;
  color: string; // hex color — use style={{ backgroundColor }} to avoid Tailwind JIT purge
}

/**
 * Hex color per activity/specialist type for map marker pins.
 *
 * DS exception: Mapbox GL markers require inline hex color values for
 * dynamic backgroundColor styling — Tailwind JIT purges unknown classes.
 * Amber/orange on climbing/wildlife_safari/adventure falls under the DS
 * "specialist highlight" allowance (design-system.md §Color).
 *
 * Tier 1 = specialist types (specialist_registry.py)
 * Tier 2 = general activity categories (experience_generator)
 * Logistics = flight/hotel/accommodation markers
 */
const SPECIALIST_MARKER_COLORS: Record<string, string> = {
  // ── Tier 1: Specialist types ──
  diving:          '#06b6d4', // cyan-500
  hiking:          '#10b981', // emerald-500
  skiing:          '#3b82f6', // blue-500
  cycling:         '#84cc16', // lime-500
  surfing:         '#6366f1', // indigo-500
  sailing:         '#06b6d4', // cyan-500
  climbing:        '#f97316', // orange-500
  wildlife_safari: '#f59e0b', // amber-500
  // ── Tier 2: General activity categories ──
  yoga:            '#a855f7', // purple-500
  wellness:        '#8b5cf6', // violet-500
  spa:             '#8b5cf6', // violet-500
  nightlife:       '#d946ef', // fuchsia-500
  cooking:         '#ec4899', // pink-500
  culture:         '#f43f5e', // rose-500
  cultural:        '#f43f5e', // rose-500
  temples:         '#f43f5e', // rose-500
  food:            '#ef4444', // red-500
  beach:           '#10b981', // emerald-500
  shopping:        '#ec4899', // pink-500
  sightseeing:     '#0ea5e9', // sky-500
  photography:     '#0ea5e9', // sky-500
  relaxation:      '#eab308', // yellow-500
  nature:          '#22c55e', // green-500
  tours:           '#3b82f6', // blue-500
  adventure:       '#f97316', // orange-500
  family:          '#f59e0b', // amber-500
  activity:        '#a855f7', // purple-500
  // ── Logistics ──
  flight:          '#60a5fa', // blue-400
  arrival:         '#60a5fa', // blue-400
  departure:       '#60a5fa', // blue-400
  hotel:           '#71717a', // zinc-500
  accommodation:   '#71717a', // zinc-500
  stay:            '#71717a', // zinc-500
  'check-in':      '#71717a', // zinc-500
  'check-out':     '#71717a', // zinc-500
};

/** Pin icon per activity/specialist type for map markers. */
const PIN_ICON: Record<string, LucideIcon> = {
  // ── Tier 1: Specialist types ──
  diving:          Waves,
  hiking:          Mountain,
  skiing:          Snowflake,
  cycling:         Bike,
  surfing:         Wind,
  sailing:         Anchor,
  climbing:        Compass,
  wildlife_safari: Binoculars,
  // ── Tier 2: General activity categories ──
  yoga:            Flower2,
  wellness:        Dumbbell,
  spa:             Flower2,
  nightlife:       Music,
  cooking:         Utensils,
  culture:         Church,
  cultural:        Church,
  temples:         Landmark,
  food:            Utensils,
  beach:           Palmtree,
  shopping:        ShoppingBag,
  sightseeing:     Camera,
  photography:     Camera,
  relaxation:      Sunset,
  nature:          Palmtree,
  tours:           Camera,
  adventure:       Compass,
  family:          Landmark,
  activity:        Flower2,
  // ── Logistics ──
  flight:          Plane,
  arrival:         Plane,
  departure:       Plane,
  hotel:           Bed,
  accommodation:   Bed,
  stay:            Bed,
  'check-in':      Bed,
  'check-out':     Bed,
};

/** Combined pin config derived from color + icon maps. */
const PIN_CONFIG: Record<string, PinConfig> = Object.fromEntries(
  Object.keys(SPECIALIST_MARKER_COLORS).map((key) => [
    key,
    { icon: PIN_ICON[key] ?? MapPin, color: SPECIALIST_MARKER_COLORS[key] },
  ])
);

// DS exception: Mapbox GL requires hex color values for marker pins
const DEFAULT_PIN: PinConfig = { icon: MapPin, color: '#a1a1aa' }; // zinc-400
const BROWSE_PIN: PinConfig = { icon: Search, color: '#f59e0b' }; // amber-500

// =============================================================================
// Helpers
// =============================================================================

const CATEGORY_LABEL: Record<string, string> = {
  cultural: 'Cultural',
  food: 'Food',
  nature: 'Nature',
  spa: 'Spa',
  tours: 'Tours',
  adventure: 'Adventure',
};

const PRICE_LEVEL_LABEL: Record<number, string> = {
  0: 'Free',
  1: '$',
  2: '$$',
  3: '$$$',
  4: '$$$$',
};

const INTENSITY_LABEL: Record<'light' | 'moderate' | 'challenging', string> = {
  light: 'Easy',
  moderate: 'Moderate',
  challenging: 'Challenging',
};

function normalizeTypeKey(type: string): string {
  return (type || '').trim().toLowerCase();
}

export function getPinConfig(type: string, source?: MapItem['source']): PinConfig {
  const normalizedType = normalizeTypeKey(type);
  const categoryPin = PIN_CONFIG[normalizedType];
  if (source === 'browse') {
    return categoryPin ?? BROWSE_PIN;
  }
  return categoryPin ?? DEFAULT_PIN;
}

function toTitleCase(value: string): string {
  return value
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function formatReviewCount(value: number): string {
  return value >= 1000 ? `${Math.round(value / 1000)}K` : value.toLocaleString();
}

function getCategoryLabel(type: string, source?: MapItem['source']): string | null {
  const normalized = normalizeTypeKey(type);
  if (!normalized) return source === 'browse' ? 'Browse' : null;
  const base = CATEGORY_LABEL[normalized] ?? toTitleCase(normalized);
  return source === 'browse' ? `Browse ${base}` : base;
}

export function normalizeMapCoordinates(
  coordinates: { lat: number; lng: number } | null | undefined
): { lat: number; lng: number } | null {
  if (!coordinates) return null;
  const lat = Number(coordinates.lat);
  const lng = Number(coordinates.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat, lng };
}

// =============================================================================
// Marker z-index styles
// =============================================================================

export const MARKER_Z_INDEX_STYLE: Record<'active' | 'hovered' | 'default', { zIndex: number }> = {
  active: { zIndex: 100 },
  hovered: { zIndex: 90 },
  default: { zIndex: 1 },
};

// =============================================================================
// MapMarkerItem — isolated per-marker component
// =============================================================================

interface MapMarkerItemProps {
  item: MapItem;
  activeItemId: string | null;
  highlightedDay?: number | null;
  onMarkerClick?: (id: string) => void;
  lastClickRef: React.RefObject<number>;
}

export const MapMarkerItem = memo(function MapMarkerItem({
  item,
  activeItemId,
  highlightedDay,
  onMarkerClick,
  lastClickRef,
}: MapMarkerItemProps) {
  // Subscribe to a boolean — only this marker re-renders on hover change
  const isStoreHovered = useUIStore((s) => s.hoveredActivityId === item.id);
  const isActive = item.id === activeItemId;
  const pin = getPinConfig(item.type, item.source);
  const MarkerIcon = pin.icon;
  // DS exception: Mapbox GL requires hex color values for marker background
  const markerBg = isActive ? '#10b981' : pin.color;
  const isDimmed =
    highlightedDay != null &&
    item.dayNumber !== undefined &&
    item.dayNumber !== highlightedDay;
  const isSpecialistPoi = item.source === 'specialist';
  const isHovered = isStoreHovered;
  const showTooltip = isActive || isHovered;
  const categoryLabel = getCategoryLabel(item.type, item.source);
  const priceLabel =
    item.priceLevel != null ? PRICE_LEVEL_LABEL[item.priceLevel] : undefined;
  const intensityLabel =
    item.intensity != null ? INTENSITY_LABEL[item.intensity] : undefined;
  const hasMeta =
    !!categoryLabel || !!intensityLabel || !!item.duration || item.rating != null || !!priceLabel;

  return (
    <Marker
      longitude={item.coordinates.lng}
      latitude={item.coordinates.lat}
      anchor="bottom"
      onClick={() => {
        const now = Date.now();
        if (now - lastClickRef.current < 500) return;
        lastClickRef.current = now;
        onMarkerClick?.(item.id);
      }}
      style={
        isActive
          ? MARKER_Z_INDEX_STYLE.active
          : isHovered
            ? MARKER_Z_INDEX_STYLE.hovered
            : MARKER_Z_INDEX_STYLE.default
      }
    >
      <div
        className={cn(
          'transition-all duration-300 transform cursor-pointer',
          isActive ? 'scale-125' : 'scale-100 hover:scale-110',
          isDimmed
            ? 'opacity-30'
            : isSpecialistPoi && !isActive
              ? 'opacity-70 hover:opacity-100'
              : 'opacity-100'
        )}
        onMouseEnter={() => { useUIStore.getState().setHoveredActivityId(item.id); }}
        onMouseLeave={() => { useUIStore.getState().setHoveredActivityId(null); }}
      >
        <div
          className={cn(
            'flex items-center justify-center rounded-full shadow-xl border-2 transition-all',
            isActive ? 'w-10 h-10 border-white' : 'w-8 h-8 border-white/80',
            isDimmed && 'grayscale'
          )}
          style={{ backgroundColor: markerBg }}
        >
          <MarkerIcon
            className="text-white"
            size={isActive ? 20 : 16}
          />
        </div>

        {item.dayNumber && !isActive && !isHovered && (
          <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-zinc-800 border border-white/30 flex items-center justify-center">
            <span className={`${DS.textSize.mapMarkerLabel} font-bold text-white`}>{item.dayNumber}</span>
          </div>
        )}

        {showTooltip && (
          <div className={`absolute top-full mt-2 left-1/2 -translate-x-1/2 z-[9999] bg-black/90 backdrop-blur-sm px-2.5 py-1.5 rounded-md ${DS.textSize.mini} text-white whitespace-nowrap pointer-events-none shadow-lg border border-white/10`}>
            <div>
              {item.dayNumber && <span className="text-emerald-400">Day {item.dayNumber} • </span>}
              <span className="font-medium">{item.title}</span>
            </div>
            {hasMeta && (
              <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-zinc-300">
                {categoryLabel && <span>{categoryLabel}</span>}
                {intensityLabel && (
                  <>
                    <span className="text-zinc-500">•</span>
                    <span>{intensityLabel}</span>
                  </>
                )}
                {item.duration && (
                  <>
                    <span className="text-zinc-500">•</span>
                    <span>{item.duration}</span>
                  </>
                )}
                {item.rating != null && (
                  <>
                    <span className="text-zinc-500">•</span>
                    <span className="inline-flex items-center gap-0.5">
                      <Star className="w-2.5 h-2.5 fill-current text-amber-400" />
                      <span>
                        {item.rating.toFixed(1)}
                        {item.reviewCount != null && ` (${formatReviewCount(item.reviewCount)})`}
                      </span>
                    </span>
                  </>
                )}
                {priceLabel && (
                  <>
                    <span className="text-zinc-500">•</span>
                    <span>{priceLabel}</span>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </Marker>
  );
});
