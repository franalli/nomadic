/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import 'mapbox-gl/dist/mapbox-gl.css';

import {
  Anchor, Bed, Bike, Binoculars, Camera, Church, Compass, Dumbbell,
  Flower2, Landmark,   type LucideIcon,
MapPin, Mountain, Music, Palmtree, Plane, ShoppingBag,
  Snowflake, Sunset, Utensils, Waves, Wind,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import MapboxMap, { type ErrorEvent, Layer, type MapRef, Marker, NavigationControl, Source } from 'react-map-gl/mapbox';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import { debugLog } from '@/lib/debug';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import { isMapboxTimingError } from './mapbox-error-handler';
export { isMapboxTimingError };

// =============================================================================
// Map Error Handler (React prop - defense in depth)
// =============================================================================

function handleMapError(event: ErrorEvent) {
  const message = event.error?.message || '';
  if (isMapboxTimingError(message)) {
    return; // Silent ignore
  }
  debugLog('[InteractiveMap] Map error:', event.error);
}

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
  source?: 'itinerary' | 'specialist';
}

export interface MapCenter {
  lat: number;
  lng: number;
  zoom: number;
}

interface InteractiveMapProps {
  items: MapItem[];
  activeItemId: string | null;
  defaultCenter: MapCenter;
  className?: string;
  onMarkerClick?: (itemId: string) => void;
  routeGeoJson?: GeoJSON.FeatureCollection | null;
  visibleLayers?: Set<string>;
  highlightedDay?: number | null;
  interactive?: boolean;
  showAttribution?: boolean;
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
 * Colors are hex (not Tailwind classes) so they survive JIT tree-shaking.
 */
const PIN_CONFIG: Record<string, PinConfig> = {
  // ── Tier 1: Specialist types ──
  diving:          { icon: Waves,       color: '#0ea5e9' }, // sky-500
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
  nightlife:       { icon: Music,       color: '#d946ef' }, // fuchsia-500
  cooking:         { icon: Utensils,    color: '#ec4899' }, // pink-500
  culture:         { icon: Church,      color: '#f43f5e' }, // rose-500
  temples:         { icon: Landmark,    color: '#fb7185' }, // rose-400
  food:            { icon: Utensils,    color: '#ef4444' }, // red-500
  beach:           { icon: Palmtree,    color: '#34d399' }, // emerald-400
  shopping:        { icon: ShoppingBag, color: '#f472b6' }, // pink-400
  sightseeing:     { icon: Camera,      color: '#38bdf8' }, // sky-400
  photography:     { icon: Camera,      color: '#7dd3fc' }, // sky-300
  relaxation:      { icon: Sunset,      color: '#fbbf24' }, // amber-400
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

const DEFAULT_PIN: PinConfig = { icon: MapPin, color: '#a1a1aa' }; // zinc-400

function getPinConfig(type: string): PinConfig {
  return PIN_CONFIG[type] ?? PIN_CONFIG[type.toLowerCase()] ?? DEFAULT_PIN;
}

function normalizeMapCoordinates(
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
// Route Layer Style
// =============================================================================

const routeLayerStyle: Omit<mapboxgl.LineLayer, 'source'> = {
  id: 'route-line',
  type: 'line',
  paint: {
    'line-color': DS.brand.emerald,
    'line-width': 3,
    'line-opacity': 0.7,
    'line-dasharray': [2, 1],
  },
};

const MARKER_Z_INDEX_STYLE: Record<'active' | 'hovered' | 'default', { zIndex: number }> = {
  active: { zIndex: 100 },
  hovered: { zIndex: 90 },
  default: { zIndex: 1 },
};

const MAP_CONTAINER_STYLE = { width: '100%', height: '100%' } as const;

// =============================================================================
// Component
// =============================================================================

export function InteractiveMap({
  items,
  activeItemId,
  defaultCenter,
  className,
  onMarkerClick,
  routeGeoJson,
  visibleLayers,
  highlightedDay,
  interactive = true,
  showAttribution = true,
}: InteractiveMapProps) {
  const isDesktop = useIsDesktop();
  const mapRef = useRef<MapRef>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const isMountedRef = useRef(true);
  const lastClickRef = useRef<number>(0);
  const [isMapReady, setIsMapReady] = useState(false);
  const [hoveredItemId, setHoveredItemId] = useState<string | null>(null);

  // Dark mode detection for map style
  const [isDark, setIsDark] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
  );

  const safeDefaultCenter = useMemo(() => {
    const normalized = normalizeMapCoordinates({
      lat: defaultCenter.lat,
      lng: defaultCenter.lng,
    });
    if (normalized) {
      return {
        lat: normalized.lat,
        lng: normalized.lng,
        zoom: defaultCenter.zoom,
      };
    }
    return { lat: 25.2048, lng: 55.2708, zoom: 10 };
  }, [defaultCenter.lat, defaultCenter.lng, defaultCenter.zoom]);

  const { normalizedItems, droppedCoordinateIds } = useMemo(() => {
    const normalized: MapItem[] = [];
    const dropped: string[] = [];
    for (const item of items) {
      const coords = normalizeMapCoordinates(item.coordinates);
      if (!coords) {
        dropped.push(item.id);
        continue;
      }
      normalized.push({ ...item, coordinates: coords });
    }
    return { normalizedItems: normalized, droppedCoordinateIds: dropped };
  }, [items]);

  const droppedCoordinateSignature = droppedCoordinateIds.join('|');

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setIsDark(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    if (!droppedCoordinateSignature) return;
    debugLog('[InteractiveMap] Skipping items with invalid coordinates', {
      dropped_count: droppedCoordinateIds.length,
      dropped_ids: droppedCoordinateIds.slice(0, 5),
    });
  }, [droppedCoordinateIds, droppedCoordinateSignature]);

  // Track mounted state for safe async operations
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Handle map load - mark as ready
  const handleMapLoad = useCallback(() => {
    if (isMountedRef.current) {
      setIsMapReady(true);
    }
  }, []);

  // Auto-fit bounds to all pins when items change (no active selection)
  useEffect(() => {
    if (!isMapReady || !mapRef.current || !isMountedRef.current) return;
    // Skip auto-fit when a specific item is actively selected
    if (activeItemId) return;
    const withCoords = normalizedItems;
    if (withCoords.length < 2) return; // Single pin uses defaultCenter zoom
    const lngs = withCoords.map((i) => i.coordinates.lng);
    const lats = withCoords.map((i) => i.coordinates.lat);
    try {
      mapRef.current.fitBounds(
        [
          [Math.min(...lngs), Math.min(...lats)],
          [Math.max(...lngs), Math.max(...lats)],
        ],
        {
          padding: isDesktop
            ? { top: 60, bottom: 60, left: 60, right: 60 }
            : { top: 30, bottom: 30, left: 30, right: 30 },
          maxZoom: 8,
          minZoom: 5,
          duration: 1000,
        }
      );
    } catch {
      // Silently ignore fitBounds errors during unmount
    }
  }, [isMapReady, normalizedItems, activeItemId, isDesktop]);

  // Scrollytelling: Fly to active item (only when map is ready)
  const flyToItem = useCallback((item: MapItem) => {
    if (!mapRef.current || !isMountedRef.current || !isMapReady) return;

    try {
      mapRef.current.flyTo({
        center: [item.coordinates.lng, item.coordinates.lat],
        zoom: 9,
        pitch: 30,
        duration: 1500,
      });
    } catch {
      // Silently ignore flyTo errors during unmount
    }
  }, [isMapReady]);

  // React to active item changes
  useEffect(() => {
    if (!activeItemId || !isMapReady) return;

    const activeItem = normalizedItems.find((i) => i.id === activeItemId);
    if (activeItem?.coordinates) {
      flyToItem(activeItem);
    }
  }, [activeItemId, normalizedItems, flyToItem, isMapReady]);

  // Track whether the user is currently panning/zooming the map
  const isUserInteractingRef = useRef(false);

  // Day-center fly-to: when highlighted day changes (from timeline scroll),
  // fly to the geographic center of that day's pins.
  // Skipped when the user is actively interacting with the map.
  useEffect(() => {
    if (highlightedDay == null || !mapRef.current || !isMapReady) return;
    if (isUserInteractingRef.current) return;

    const dayPins = normalizedItems.filter((i) => i.dayNumber === highlightedDay);
    if (dayPins.length === 0) return;

    const avgLat = dayPins.reduce((s, p) => s + p.coordinates.lat, 0) / dayPins.length;
    const avgLng = dayPins.reduce((s, p) => s + p.coordinates.lng, 0) / dayPins.length;

    try {
      mapRef.current.flyTo({
        center: [avgLng, avgLat],
        zoom: dayPins.length === 1 ? 9 : 7,
        duration: 1200,
        essential: true,
      });
    } catch {
      // Silently ignore flyTo errors during unmount
    }
  }, [highlightedDay, normalizedItems, isMapReady]);

  // ResizeObserver: tell Mapbox to remeasure when the container changes size
  // (e.g. layout column width changes, panel expand/collapse)
  useEffect(() => {
    if (!mapContainerRef.current) return;
    const observer = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    observer.observe(mapContainerRef.current);
    return () => observer.disconnect();
  }, []);

  // Check if Mapbox token is available
  const mapboxToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

  if (!mapboxToken) {
    return (
      <div className={cn('w-full h-full rounded-xl overflow-hidden border border-white/10 bg-zinc-900 flex items-center justify-center', className)}>
        <div className="text-center p-6">
          <MapPin className="w-12 h-12 text-zinc-600 mx-auto mb-3" />
          <p className="text-sm text-zinc-400">Interactive Map</p>
          <p className="text-xs text-zinc-500 mt-1">
            Configure NEXT_PUBLIC_MAPBOX_TOKEN to enable
          </p>
        </div>
      </div>
    );
  }

  // Filter items by visible layers
  const filteredItems = visibleLayers
    ? normalizedItems.filter((item) => visibleLayers.has(item.type))
    : normalizedItems;

  return (
    <div ref={mapContainerRef} className={cn('w-full h-full rounded-xl overflow-hidden border border-zinc-200 dark:border-white/10', className)}>
      <MapboxMap
        ref={mapRef}
        initialViewState={{
          longitude: safeDefaultCenter.lng,
          latitude: safeDefaultCenter.lat,
          zoom: safeDefaultCenter.zoom,
        }}
        style={MAP_CONTAINER_STYLE}
        mapStyle={isDark ? 'mapbox://styles/mapbox/dark-v11' : 'mapbox://styles/mapbox/light-v11'}
        mapboxAccessToken={mapboxToken}
        // Disable Mapbox metrics collection to avoid blocked telemetry requests in ad-blocking browsers.
        performanceMetricsCollection={false}
        interactive={interactive}
        attributionControl={showAttribution}
        onError={handleMapError}
        onLoad={handleMapLoad}
        onMoveStart={() => {
          isUserInteractingRef.current = true;
          setHoveredItemId(null); // clear stale tooltip when map pans
        }}
        onMoveEnd={() => { isUserInteractingRef.current = false; }}
        // Reuse maps to prevent recreation issues
        reuseMaps
      >
        {interactive && <NavigationControl position="bottom-right" />}

        {routeGeoJson && (
          <Source id="route" type="geojson" data={routeGeoJson}>
            <Layer {...routeLayerStyle} />
          </Source>
        )}

        {filteredItems.length === 0 && (
          <Marker
            latitude={safeDefaultCenter.lat}
            longitude={safeDefaultCenter.lng}
            anchor="bottom"
          >
            <div className="relative">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-10 h-10 rounded-full bg-emerald-400 animate-ping opacity-20" />
              </div>
              <MapPin
                className={`relative w-10 h-10 text-emerald-400 ${DS.glowClass.dropMarker}`}
              />
            </div>
          </Marker>
        )}

        {filteredItems.map((item) => {
          const isActive = item.id === activeItemId;
          const pin = getPinConfig(item.type);
          const MarkerIcon = pin.icon;
          const markerBg = isActive ? '#10b981' : pin.color; // emerald-500 when active
          const isDimmed =
            highlightedDay != null &&
            item.dayNumber !== undefined &&
            item.dayNumber !== highlightedDay;
          const isSpecialistPoi = item.source === 'specialist';
          const isHovered = item.id === hoveredItemId;
          const showTooltip = isActive || isHovered;

          return (
            <Marker
              key={item.id}
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
                  isActive ? 'scale-125' : isHovered ? 'scale-110' : 'scale-100',
                  isDimmed
                    ? 'opacity-30'
                    : isSpecialistPoi && !isActive && !isHovered
                      ? 'opacity-70 hover:opacity-100'
                      : 'opacity-100 hover:opacity-100'
                )}
                onMouseEnter={() => setHoveredItemId(item.id)}
                onMouseLeave={() => setHoveredItemId(null)}
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
                    {item.dayNumber && <span className="text-emerald-400">Day {item.dayNumber} • </span>}
                    <span className="font-medium">{item.title}</span>
                    {!item.dayNumber && <span className="text-zinc-400 ml-1">· {item.type}</span>}
                  </div>
                )}
              </div>
            </Marker>
          );
        })}
      </MapboxMap>
    </div>
  );
}

export default InteractiveMap;
