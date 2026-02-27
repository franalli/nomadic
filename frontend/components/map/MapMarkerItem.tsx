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
 * Pin icon + color per activity/specialist type.
 * Keys match backend `specialist_type` and `activity_type` values exactly.
 * Tier 1 = specialist types (specialist_registry.py)
 * Tier 2 = general activity categories (experience_generator)
 *
 * DS exception: Mapbox GL markers require inline hex color values for
 * dynamic backgroundColor styling — Tailwind JIT purges unknown classes.
 */
const PIN_CONFIG: Record<string, PinConfig> = {
  // ── Tier 1: Specialist types ──
  diving:          { icon: Waves,       color: '#06b6d4' }, // cyan-500
  hiking:          { icon: Mountain,    color: '#10b981' }, // emerald-500
  skiing:          { icon: Snowflake,   color: '#3b82f6' }, // blue-500
  cycling:         { icon: Bike,        color: '#84cc16' }, // lime-500
  surfing:         { icon: Wind,        color: '#6366f1' }, // indigo-500
  sailing:         { icon: Anchor,      color: '#06b6d4' }, // cyan-500
  climbing:        { icon: Compass,     color: '#f97316' }, // orange-500
  wildlife_safari: { icon: Binoculars,  color: '#f59e0b' }, // amber-500
  // ── Tier 2: General activity categories ──
  yoga:            { icon: Flower2,     color: '#a855f7' }, // purple-500
  wellness:        { icon: Dumbbell,    color: '#8b5cf6' }, // violet-500
  spa:             { icon: Flower2,     color: '#8b5cf6' }, // violet-500
  nightlife:       { icon: Music,       color: '#d946ef' }, // fuchsia-500
  cooking:         { icon: Utensils,    color: '#ec4899' }, // pink-500
  culture:         { icon: Church,      color: '#f43f5e' }, // rose-500
  cultural:        { icon: Church,      color: '#f43f5e' }, // rose-500
  temples:         { icon: Landmark,    color: '#f43f5e' }, // rose-500
  food:            { icon: Utensils,    color: '#ef4444' }, // red-500
  beach:           { icon: Palmtree,    color: '#10b981' }, // emerald-500
  shopping:        { icon: ShoppingBag, color: '#ec4899' }, // pink-500
  sightseeing:     { icon: Camera,      color: '#0ea5e9' }, // sky-500
  photography:     { icon: Camera,      color: '#0ea5e9' }, // sky-500
  relaxation:      { icon: Sunset,      color: '#eab308' }, // yellow-500
  nature:          { icon: Palmtree,    color: '#22c55e' }, // green-500
  tours:           { icon: Camera,      color: '#3b82f6' }, // blue-500
  adventure:       { icon: Compass,     color: '#f97316' }, // orange-500
  family:          { icon: Landmark,    color: '#f59e0b' }, // amber-500
  activity:        { icon: Flower2,     color: '#a855f7' }, // purple-500
  // ── Logistics ──
  flight:          { icon: Plane,       color: '#60a5fa' }, // blue-400
  arrival:         { icon: Plane,       color: '#60a5fa' }, // blue-400
  departure:       { icon: Plane,       color: '#60a5fa' }, // blue-400
  hotel:           { icon: Bed,         color: '#71717a' }, // zinc-500
  accommodation:   { icon: Bed,         color: '#71717a' }, // zinc-500
  stay:            { icon: Bed,         color: '#71717a' }, // zinc-500
  'check-in':      { icon: Bed,         color: '#71717a' }, // zinc-500
  'check-out':     { icon: Bed,         color: '#71717a' }, // zinc-500
};

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
