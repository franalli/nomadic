'use client';

import 'mapbox-gl/dist/mapbox-gl.css';

import { Bed, Camera, Landmark, MapPin, Mountain, Plane, Utensils, Waves } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import Map, { type ErrorEvent, Layer, type MapRef, Marker, NavigationControl, Source } from 'react-map-gl/mapbox';

import { cn } from '@/lib/utils';

// =============================================================================
// Comprehensive Global Error Suppression for Mapbox
// =============================================================================

/**
 * Known Mapbox timing errors that are harmless and should be suppressed.
 * These occur when the map is destroyed during async operations.
 */
const SUPPRESSED_ERROR_PATTERNS = [
  'errorCb is not a function',
  'this.errorCb is not a function',
  'Map container is already removed',
  'Cannot read properties of undefined',
  'Cannot read properties of null',
  'sku_token',
  'mapbox-gl',
];

/**
 * Check if an error message matches known Mapbox timing issues.
 */
function isMapboxTimingError(input: string | Error | unknown): boolean {
  let message = '';

  if (typeof input === 'string') {
    message = input;
  } else if (input instanceof Error) {
    message = input.message || input.toString();
  } else if (input && typeof input === 'object') {
    message = (input as { message?: string }).message || String(input);
  }

  return SUPPRESSED_ERROR_PATTERNS.some((pattern) => message.includes(pattern));
}

// Install comprehensive error suppression ONCE
let _globalHandlerInstalled = false;

function installGlobalMapboxErrorHandler(): void {
  if (_globalHandlerInstalled || typeof window === 'undefined') return;
  _globalHandlerInstalled = true;

  // Store original handlers
  const originalOnError = window.onerror;

  // Override window.onerror (catches errors before React/Next.js error boundary)
  window.onerror = function (
    message: string | Event,
    source?: string,
    lineno?: number,
    colno?: number,
    error?: Error
  ): boolean {
    const msgStr = typeof message === 'string' ? message : '';
    const isMapboxError = isMapboxTimingError(msgStr) || isMapboxTimingError(error);

    // Check if error is from mapbox-gl source files
    const isMapboxSource = source?.includes('mapbox-gl') || source?.includes('sku_token');

    if (isMapboxError || isMapboxSource) {
      // Suppress - return true to prevent default handling
      return true;
    }

    // Call original handler if exists
    if (originalOnError) {
      return originalOnError.call(window, message, source, lineno, colno, error);
    }
    return false;
  };

  // Capture phase listener (runs before bubble phase handlers)
  window.addEventListener(
    'error',
    (event) => {
      const errorEvent = event as globalThis.ErrorEvent;
      const message = errorEvent.message || errorEvent.error?.message || '';
      const filename = errorEvent.filename || '';

      const isMapboxError = isMapboxTimingError(message) || isMapboxTimingError(errorEvent.error);
      const isMapboxSource = filename.includes('mapbox-gl') || filename.includes('sku_token');

      if (isMapboxError || isMapboxSource) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return true;
      }
    },
    true // Capture phase
  );

  // Bubble phase listener (backup)
  window.addEventListener('error', (event) => {
    const errorEvent = event as globalThis.ErrorEvent;
    const message = errorEvent.message || errorEvent.error?.message || '';
    if (isMapboxTimingError(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return true;
    }
  });

  // Handle unhandled promise rejections
  window.addEventListener(
    'unhandledrejection',
    (event: PromiseRejectionEvent) => {
      if (isMapboxTimingError(event.reason)) {
        event.preventDefault();
        return true;
      }
    },
    true
  );
}

// Install handler immediately when module loads
installGlobalMapboxErrorHandler();

// =============================================================================
// Map Error Handler (React prop - defense in depth)
// =============================================================================

function handleMapError(event: ErrorEvent) {
  const message = event.error?.message || '';
  if (isMapboxTimingError(message)) {
    return; // Silent ignore
  }
  console.warn('[InteractiveMap] Map error:', event.error);
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

  if (lowerType === 'diving' || lowerType.includes('dive')) return 'bg-cyan-500';
  if (lowerType === 'hiking' || lowerType.includes('hike')) return 'bg-green-500';
  if (lowerType.includes('hotel') || lowerType.includes('stay')) return 'bg-purple-500';
  if (lowerType.includes('flight')) return 'bg-blue-500';
  if (lowerType.includes('temple')) return 'bg-amber-500';
  if (lowerType.includes('food')) return 'bg-orange-500';

  return 'bg-emerald-500';
}

// =============================================================================
// Route Layer Style
// =============================================================================

const routeLayerStyle: Omit<mapboxgl.LineLayer, 'source'> = {
  id: 'route-line',
  type: 'line',
  paint: {
    'line-color': '#10b981',
    'line-width': 3,
    'line-opacity': 0.7,
    'line-dasharray': [2, 1],
  },
};

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
  const mapRef = useRef<MapRef>(null);
  const isMountedRef = useRef(true);
  const [isMapReady, setIsMapReady] = useState(false);

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

    const activeItem = items.find((i) => i.id === activeItemId);
    if (activeItem?.coordinates) {
      flyToItem(activeItem);
    }
  }, [activeItemId, items, flyToItem, isMapReady]);

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
    ? items.filter((item) => visibleLayers.has(item.type))
    : items;

  return (
    <div className={cn('w-full h-full rounded-xl overflow-hidden border border-white/10', className)}>
      <Map
        ref={mapRef}
        initialViewState={{
          longitude: defaultCenter.lng,
          latitude: defaultCenter.lat,
          zoom: defaultCenter.zoom,
        }}
        style={{ width: '100%', height: '100%' }}
        mapStyle="mapbox://styles/mapbox/dark-v11"
        mapboxAccessToken={mapboxToken}
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
            longitude={defaultCenter.lng}
            latitude={defaultCenter.lat}
            anchor="bottom"
          >
            <div className="relative">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-10 h-10 rounded-full bg-emerald-400 animate-ping opacity-20" />
              </div>
              <MapPin
                className="relative w-10 h-10 text-emerald-400 drop-shadow-[0_2px_8px_rgba(16,185,129,0.6)]"
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

          return (
            <Marker
              key={item.id}
              longitude={item.coordinates.lng}
              latitude={item.coordinates.lat}
              anchor="bottom"
              onClick={() => onMarkerClick?.(item.id)}
            >
              <div
                className={cn(
                  'transition-all duration-300 transform cursor-pointer',
                  isActive ? 'scale-125 z-50' : 'scale-100',
                  isDimmed
                    ? 'opacity-30'
                    : isSpecialistPoi && !isActive
                      ? 'opacity-70 hover:opacity-100'
                      : 'opacity-100 hover:opacity-100'
                )}
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

                {item.dayNumber && !isActive && (
                  <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-zinc-800 border border-white/30 flex items-center justify-center">
                    <span className="text-[8px] font-bold text-white">{item.dayNumber}</span>
                  </div>
                )}

                {isActive && (
                  <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 bg-black/80 backdrop-blur px-2 py-1 rounded text-[10px] text-white whitespace-nowrap pointer-events-none">
                    {item.dayNumber && <span className="text-emerald-400">Day {item.dayNumber} • </span>}
                    {item.title}
                  </div>
                )}
              </div>
            </Marker>
          );
        })}
      </Map>
    </div>
  );
}

export default InteractiveMap;
