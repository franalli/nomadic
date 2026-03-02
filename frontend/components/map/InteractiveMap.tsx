/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import 'mapbox-gl/dist/mapbox-gl.css';

import { MapPin } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import MapboxMap, { type ErrorEvent, Layer, type MapRef, Marker, Source } from 'react-map-gl/mapbox';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import { debugLog } from '@/lib/debug';
import { DS } from '@/lib/design-system';
import { isDarkTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/state/uiStore';

import { isMapboxTimingError } from './mapbox-error-handler';
import { type MapCenter,type MapItem, MapMarkerItem, normalizeMapCoordinates } from './MapMarkerItem';
// Re-export types for external consumers
export type { MapCenter,MapItem };
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

interface InteractiveMapProps {
  items: MapItem[];
  activeItemId: string | null;
  defaultCenter: MapCenter;
  className?: string;
  onMarkerClick?: (itemId: string) => void;
  /** Card→map: highlight this pin when a day-card block is hovered */
  externalHoveredItemId?: string | null;
  /** Map→card: fires when a pin is hovered/unhovered */
  onMarkerHover?: (itemId: string | null) => void;
  routeGeoJson?: GeoJSON.FeatureCollection | null;
  visibleLayers?: Set<string>;
  highlightedDay?: number | null;
  interactive?: boolean;
  showAttribution?: boolean;
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

  const isDark = isDarkTheme();

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
    return { lat: 0, lng: 0, zoom: 2 };
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
          maxZoom: 14,
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
          useUIStore.getState().setHoveredActivityId(null); // clear stale tooltip when map pans
        }}
        onMoveEnd={() => { isUserInteractingRef.current = false; }}
        // Reuse maps to prevent recreation issues
        reuseMaps
      >
{/* Navigation controls hidden — map interaction via gestures only */}

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

        {filteredItems.map((item) => (
          <MapMarkerItem
            key={item.id}
            item={item}
            activeItemId={activeItemId}
            highlightedDay={highlightedDay}
            onMarkerClick={onMarkerClick}
            lastClickRef={lastClickRef}
          />
        ))}
      </MapboxMap>
    </div>
  );
}

export default InteractiveMap;
