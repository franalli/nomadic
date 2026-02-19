/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import 'mapbox-gl/dist/mapbox-gl.css';

import { Bed, Camera, Landmark, MapPin, Mountain, Plane, Utensils, Waves } from 'lucide-react';
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
// Icon Helpers
// =============================================================================

function getMarkerIcon(type: string) {
  const lowerType = type.toLowerCase();

  if (lowerType.includes('flight') || lowerType.includes('arrival') || lowerType.includes('departure')) {
    return Plane;
  }
  if (lowerType.includes('hotel') || lowerType.includes('stay') || lowerType.includes('accommodation')) {
    return Bed;
  }
  if (lowerType === 'diving' || lowerType.includes('dive') || lowerType.includes('snorkel') || lowerType.includes('water')) {
    return Waves;
  }
  if (lowerType === 'hiking' || lowerType.includes('hike') || lowerType.includes('trek') || lowerType.includes('mountain')) {
    return Mountain;
  }
  if (lowerType.includes('temple') || lowerType.includes('shrine') || lowerType.includes('landmark')) {
    return Landmark;
  }
  if (lowerType.includes('food') || lowerType.includes('restaurant') || lowerType.includes('dining')) {
    return Utensils;
  }
  if (lowerType.includes('tour') || lowerType.includes('sightseeing')) {
    return Camera;
  }

  return MapPin;
}

function getMarkerColor(type: string): string {
  const lowerType = type.toLowerCase();

  // Specialist activity types (mirrors frontend/lib/specialists.ts colors)
  if (lowerType === 'diving' || lowerType.includes('dive')) return 'bg-sky-500';
  if (lowerType === 'hiking' || lowerType.includes('hike')) return 'bg-emerald-500';
  if (lowerType === 'surfing' || lowerType.includes('surf')) return 'bg-indigo-500';
  if (lowerType === 'skiing' || lowerType.includes('ski')) return 'bg-blue-500';
  if (lowerType === 'cycling' || lowerType.includes('cycl') || lowerType.includes('bike')) return 'bg-lime-500';
  if (lowerType === 'sailing' || lowerType === 'boating' || lowerType.includes('sail')) return 'bg-cyan-500';
  if (lowerType === 'climbing' || lowerType.includes('climb')) return 'bg-orange-500';
  if (lowerType === 'wildlife_safari' || lowerType.includes('safari')) return 'bg-amber-500';
  // Tier 2 categories
  if (lowerType === 'yoga' || lowerType === 'wellness') return 'bg-violet-500';
  if (lowerType === 'cooking') return 'bg-pink-500';
  if (lowerType === 'nightlife') return 'bg-fuchsia-500';
  // Logistics / other
  if (lowerType.includes('hotel') || lowerType.includes('stay')) return 'bg-purple-500';
  if (lowerType.includes('flight')) return 'bg-slate-500';
  if (lowerType.includes('temple')) return 'bg-rose-500';
  if (lowerType.includes('food')) return 'bg-pink-500';

  return 'bg-emerald-500';
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
  const isMountedRef = useRef(true);
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
            ? { top: 40, bottom: 40, left: 40, right: 40 }
            : { top: 20, bottom: 20, left: 20, right: 20 },
          maxZoom: 12,
          minZoom: 7,
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
        zoom: 13,
        pitch: 45,
        duration: 2000,
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

  // Check if Mapbox token is available
  const mapboxToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

  if (!mapboxToken) {
    return (
      <div className={cn('w-full h-full rounded-xl overflow-hidden border border-white/10 bg-zinc-900 flex items-center justify-center', className)}>
        <div className="text-center p-6">
          <MapPin className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">Interactive Map</p>
          <p className="text-xs text-muted-foreground/60 mt-1">
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
    <div className={cn('w-full h-full rounded-xl overflow-hidden border border-zinc-200 dark:border-white/10', className)}>
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
          const MarkerIcon = getMarkerIcon(item.type);
          const markerColor = isActive ? 'bg-emerald-500' : getMarkerColor(item.type);
          const isDimmed =
            highlightedDay !== null &&
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
              onClick={() => onMarkerClick?.(item.id)}
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
                    isActive
                      ? 'w-10 h-10 bg-emerald-500 border-white'
                      : `w-8 h-8 ${markerColor} border-white/80`,
                    isDimmed && 'grayscale'
                  )}
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
