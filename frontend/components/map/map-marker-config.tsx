import {
  Anchor,
  Bed,
  Bike,
  Binoculars,
  Camera,
  Church,
  Compass,
  Dumbbell,
  Flower2,
  Landmark,
  type LucideIcon,
  MapPin,
  Mountain,
  Music,
  Palmtree,
  Plane,
  Search,
  ShoppingBag,
  Snowflake,
  Sunset,
  Utensils,
  Waves,
} from 'lucide-react';

import { DS } from '@/lib/design-system';
import { getSpecialistColor } from '@/lib/specialists';

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

export interface MapCenter { lat: number; lng: number; zoom: number }
export interface PinConfig { icon: LucideIcon; color: string }

const MAP_LOGISTICS_COLORS: Record<string, string> = {
  flight: DS.map.flight,
  arrival: DS.map.flight,
  departure: DS.map.flight,
  hotel: DS.brand.emerald,
  accommodation: DS.brand.emerald,
  lodging: DS.brand.emerald,
  stay: DS.brand.emerald,
  'check-in': DS.brand.emerald,
  'check-out': DS.brand.emerald,
  check_in: DS.brand.emerald,
  check_out: DS.brand.emerald,
  family: DS.map.family,
  activity: DS.map.activity,
};

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

const PIN_ICON: Record<string, LucideIcon> = {
  diving: Waves,
  hiking: Mountain,
  skiing: Snowflake,
  cycling: Bike,
  surfing: SurfboardIcon as unknown as LucideIcon,
  sailing: Anchor,
  climbing: Compass,
  wildlife_safari: Binoculars,
  yoga: Flower2,
  wellness: Dumbbell,
  spa: Flower2,
  nightlife: Music,
  cooking: Utensils,
  culture: Church,
  cultural: Church,
  temples: Landmark,
  food: Utensils,
  beach: Palmtree,
  shopping: ShoppingBag,
  sightseeing: Camera,
  photography: Camera,
  relaxation: Sunset,
  nature: Palmtree,
  tours: Camera,
  adventure: Compass,
  family: Landmark,
  activity: Flower2,
  flight: Plane,
  arrival: Plane,
  departure: Plane,
  hotel: Bed,
  accommodation: Bed,
  stay: Bed,
  'check-in': Bed,
  'check-out': Bed,
  check_in: Bed,
  check_out: Bed,
  lodging: Bed,
};

const CATEGORY_LABEL: Record<string, string> = { cultural: 'Cultural', food: 'Food', nature: 'Nature', spa: 'Spa', tours: 'Tours', adventure: 'Adventure' };
const PRICE_LEVEL_LABEL: Record<number, string> = { 0: 'Free', 1: '$', 2: '$$', 3: '$$$', 4: '$$$$' };
const INTENSITY_LABEL: Record<'light' | 'moderate' | 'challenging', string> = { light: 'Easy', moderate: 'Moderate', challenging: 'Challenging' };

const PIN_CONFIG: Record<string, PinConfig> = Object.fromEntries(
  Object.keys(PIN_ICON).map((key) => [
    key,
    { icon: PIN_ICON[key] ?? MapPin, color: MAP_LOGISTICS_COLORS[key] ?? getSpecialistColor(key) },
  ])
);

const DEFAULT_PIN: PinConfig = { icon: MapPin, color: DS.map.defaultPin };
const BROWSE_PIN: PinConfig = { icon: Search, color: DS.map.browsePin };

export const MARKER_Z_INDEX_STYLE: Record<'active' | 'hovered' | 'default', { zIndex: number }> = { active: { zIndex: 100 }, hovered: { zIndex: 90 }, default: { zIndex: 1 } };

function normalizeTypeKey(type: string): string {
  return (type || '').trim().toLowerCase();
}

function toTitleCase(value: string): string {
  return value
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function getMarkerColor(type: string): string {
  return MAP_LOGISTICS_COLORS[type] ?? getSpecialistColor(type);
}

export function getPinConfig(type: string, source?: MapItem['source']): PinConfig {
  const normalizedType = normalizeTypeKey(type);
  const categoryPin = PIN_CONFIG[normalizedType];
  if (categoryPin) return categoryPin;

  const color = getMarkerColor(normalizedType);
  const fallbackDefault = color !== getSpecialistColor() ? { icon: MapPin, color } : null;
  if (source === 'browse') {
    return fallbackDefault ?? BROWSE_PIN;
  }
  return fallbackDefault ?? DEFAULT_PIN;
}

export function getCategoryLabel(type: string, source?: MapItem['source']): string | null {
  const normalized = normalizeTypeKey(type);
  if (!normalized) return source === 'browse' ? 'Browse' : null;
  const base = CATEGORY_LABEL[normalized] ?? toTitleCase(normalized);
  return source === 'browse' ? `Browse ${base}` : base;
}

export function getIntensityLabel(intensity?: MapItem['intensity']): string | undefined {
  return intensity ? INTENSITY_LABEL[intensity] : undefined;
}

export function getPriceLabel(priceLevel?: number): string | undefined {
  return priceLevel != null ? PRICE_LEVEL_LABEL[priceLevel] : undefined;
}

export function formatReviewCount(value: number): string {
  return value >= 1000 ? `${Math.round(value / 1000)}K` : value.toLocaleString();
}

export function normalizeMapCoordinates(coordinates: { lat: number; lng: number } | null | undefined): { lat: number; lng: number } | null {
  if (!coordinates) return null;
  const lat = Number(coordinates.lat);
  const lng = Number(coordinates.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat, lng };
}
