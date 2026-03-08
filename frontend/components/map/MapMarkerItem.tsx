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
  Sunset, Utensils, Waves,
} from 'lucide-react';
import { memo } from 'react';
import { Marker } from 'react-map-gl/mapbox';

import { DS } from '@/lib/design-system';
import { getSpecialistColor } from '@/lib/specialists';
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
 * Map-only color overrides for logistics and uncategorized marker types
 * not covered by getSpecialistColor() from specialists.ts (the SSoT).
 *
 * DS exception: Mapbox GL markers require inline hex color values for
 * dynamic backgroundColor styling — Tailwind JIT purges unknown classes.
 */
const MAP_LOGISTICS_COLORS: Record<string, string> = {
  flight:          '#60a5fa', // blue-400
  arrival:         '#60a5fa', // blue-400
  departure:       '#60a5fa', // blue-400
  hotel:           '#10b981', // emerald-500
  accommodation:   '#10b981', // emerald-500
  lodging:         '#10b981', // emerald-500
  stay:            '#10b981', // emerald-500
  'check-in':      '#10b981', // emerald-500
  'check-out':     '#10b981', // emerald-500
  check_in:        '#10b981', // emerald-500
  check_out:       '#10b981', // emerald-500
  family:          '#f59e0b', // amber-500
  activity:        '#a855f7', // purple-500
};

/** Horizontal surfboard icon for surfing map markers. */
function SurfboardIcon({ className, size = 16 }: { className?: string; size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <ellipse cx="12" cy="12" rx="11" ry="3.5" />
      <line x1="8" y1="12" x2="5" y2="9.5" />
    </svg>
  );
}

/** Pin icon per activity/specialist type for map markers. */
const PIN_ICON: Record<string, LucideIcon> = {
  // ── Tier 1: Specialist types ──
  diving:          Waves,
  hiking:          Mountain,
  skiing:          Snowflake,
  cycling:         Bike,
  surfing:         SurfboardIcon as unknown as LucideIcon,
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
  check_in:        Bed,
  check_out:       Bed,
  lodging:         Bed,
};

/** Resolve marker hex color: logistics local map, then specialist SSoT. */
function getMarkerColor(type: string): string {
  return MAP_LOGISTICS_COLORS[type] ?? getSpecialistColor(type);
}

/** Combined pin config derived from icon map + color resolution. */
const PIN_CONFIG: Record<string, PinConfig> = Object.fromEntries(
  Object.keys(PIN_ICON).map((key) => [
    key,
    { icon: PIN_ICON[key] ?? MapPin, color: getMarkerColor(key) },
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
  if (categoryPin) return categoryPin;
  // Fallback: type not in PIN_ICON but may have a specialist color
  const color = getMarkerColor(normalizedType);
  const fallbackDefault = color !== getSpecialistColor() ? { icon: MapPin, color } : null;
  if (source === 'browse') {
    return fallbackDefault ?? BROWSE_PIN;
  }
  return fallbackDefault ?? DEFAULT_PIN;
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
            isActive
              ? 'ring-2 ring-emerald-300/85 shadow-[0_0_16px_rgba(16,185,129,0.45)]'
              : isHovered && 'ring-2 ring-emerald-400/80 shadow-[0_0_12px_rgba(16,185,129,0.35)]',
            isDimmed && 'grayscale'
          )}
          style={{ backgroundColor: markerBg }}
        >
          <MarkerIcon
            className="text-white"
            size={isActive ? 20 : isHovered ? 18 : 16}
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
              <div className={`mt-0.5 flex items-center gap-1.5 ${DS.textSize.micro} text-zinc-300`}>
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
                      <Star className="w-2.5 h-2.5 fill-current text-zinc-400 dark:text-zinc-500" />
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
