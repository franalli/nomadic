/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import 'mapbox-gl/dist/mapbox-gl.css';

import { MapPin } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import MapboxMap, { Layer, type MapRef, Marker, Source } from 'react-map-gl/mapbox';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import { DS } from '@/lib/design-system';
import { isDarkTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/state/uiStore';

import {
  getSafeDefaultCenter,
  handleMapError,
  MAP_CONTAINER_STYLE,
  MapTokenMissingState,
  normalizeMapItems,
  routeLayerStyle,
  useActiveItemFlyTo,
  useAutoFitBounds,
  useDroppedCoordinateLogging,
  useHighlightedDayFlyTo,
  useMapResizeObserver,
  useMountedFlag,
} from './InteractiveMapHelpers';
import { isMapboxTimingError } from './mapbox-error-handler';
import { type MapCenter, type MapItem, MapMarkerItem } from './MapMarkerItem';
// Re-export types for external consumers
export type { MapCenter, MapItem };
export { isMapboxTimingError };

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
  const safeDefaultCenter = useMemo(() => getSafeDefaultCenter(defaultCenter), [defaultCenter]);
  const { normalizedItems, droppedCoordinateIds } = useMemo(() => normalizeMapItems(items), [items]);

  useDroppedCoordinateLogging(droppedCoordinateIds);
  useMountedFlag(isMountedRef);

  // Handle map load - mark as ready
  const handleMapLoad = useCallback(() => {
    if (isMountedRef.current) {
      setIsMapReady(true);
    }
  }, []);

  const isUserInteractingRef = useRef(false);
  useAutoFitBounds({
    activeItemId,
    isDesktop,
    isMapReady,
    isMountedRef,
    mapRef,
    normalizedItems,
  });
  useActiveItemFlyTo({ activeItemId, isMapReady, isMountedRef, mapRef, normalizedItems });
  useHighlightedDayFlyTo({
    highlightedDay,
    isMapReady,
    isUserInteractingRef,
    mapRef,
    normalizedItems,
  });
  useMapResizeObserver({ mapContainerRef, mapRef });

  // Check if Mapbox token is available
  const mapboxToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

  if (!mapboxToken) {
    return <MapTokenMissingState className={className} />;
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
        {routeGeoJson && (
          <Source id="route" type="geojson" data={routeGeoJson}>
            <Layer {...routeLayerStyle} />
          </Source>
        )}

        {filteredItems.length === 0 ? (
          <Marker latitude={safeDefaultCenter.lat} longitude={safeDefaultCenter.lng} anchor="bottom">
            <div className="relative">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="h-10 w-10 animate-ping rounded-full bg-emerald-400 opacity-20" />
              </div>
              <MapPin className={`relative h-10 w-10 text-emerald-400 ${DS.glowClass.dropMarker}`} />
            </div>
          </Marker>
        ) : null}

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
