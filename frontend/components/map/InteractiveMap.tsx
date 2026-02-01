'use client';

import 'mapbox-gl/dist/mapbox-gl.css';

import { Bed, Camera, Landmark, MapPin, Mountain, Plane, Utensils, Waves } from 'lucide-react';
import { useCallback, useEffect, useRef } from 'react';
import Map, { type MapRef, Layer, Marker, NavigationControl, Source } from 'react-map-gl/mapbox';

import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

/**
 * Map item with coordinates for marker placement
 */
export interface MapItem {
  id: string;
  title: string;
  type: string;
  coordinates: { lat: number; lng: number };
  dayNumber?: number;
  period?: 'morning' | 'afternoon' | 'evening';
  source?: 'itinerary' | 'specialist';
}

/**
 * Default center for map initialization
 */
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
  /** Callback when marker is clicked */
  onMarkerClick?: (itemId: string) => void;
  /** GeoJSON route for line visualization */
  routeGeoJson?: GeoJSON.FeatureCollection | null;
  /** Set of visible layer types (for filtering) */
  visibleLayers?: Set<string>;
  /** Highlighted day number (dims other days) */
  highlightedDay?: number | null;
  /** Disable pan/zoom for static display (MVP) */
  interactive?: boolean;
  /** Hide attribution for cleaner static display */
  showAttribution?: boolean;
}

// =============================================================================
// Icon Helpers
// =============================================================================

/**
 * Get icon component based on item type
 */
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

/**
 * Get marker background color based on type
 */
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
    'line-color': '#10b981', // emerald-500
    'line-width': 3,
    'line-opacity': 0.7,
    'line-dasharray': [2, 1],
  },
};

// =============================================================================
// Component
// =============================================================================

/**
 * InteractiveMap
 *
 * Mapbox-powered scrollytelling map for Plan view.
 * Features:
 * - Smooth flyTo animations when active item changes
 * - 3D pitch for cinematic effect
 * - Marker scaling and highlighting for active item
 * - Route line visualization
 * - Layer filtering support
 * - Click handlers for two-way navigation
 * - Dark mode styling
 */
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

  // Scrollytelling: Fly to active item
  const flyToItem = useCallback((item: MapItem) => {
    if (!mapRef.current) return;

    mapRef.current.flyTo({
      center: [item.coordinates.lng, item.coordinates.lat],
      zoom: 13,
      pitch: 45, // 3D cinematic effect
      duration: 2000, // Smooth 2-second transition
    });
  }, []);

  // React to active item changes
  useEffect(() => {
    if (!activeItemId) return;

    const activeItem = items.find((i) => i.id === activeItemId);
    if (activeItem?.coordinates) {
      flyToItem(activeItem);
    }
  }, [activeItemId, items, flyToItem]);

  // Check if Mapbox token is available
  const mapboxToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

  if (!mapboxToken) {
    // Fallback UI when Mapbox token is not configured
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
      >
        {/* Navigation control - only when interactive */}
        {interactive && <NavigationControl position="bottom-right" />}

        {/* Route line layer */}
        {routeGeoJson && (
          <Source id="route" type="geojson" data={routeGeoJson}>
            <Layer {...routeLayerStyle} />
          </Source>
        )}

        {/* Static destination pin with pulse - shown when no POI items */}
        {filteredItems.length === 0 && (
          <Marker
            longitude={defaultCenter.lng}
            latitude={defaultCenter.lat}
            anchor="bottom"
          >
            <div className="relative">
              {/* Pulse ring animation */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-10 h-10 rounded-full bg-emerald-400 animate-ping opacity-20" />
              </div>
              {/* Pin icon */}
              <MapPin
                className="relative w-10 h-10 text-emerald-400 drop-shadow-[0_2px_8px_rgba(16,185,129,0.6)]"
              />
            </div>
          </Marker>
        )}

        {/* Render markers for all items with coordinates */}
        {filteredItems.map((item) => {
          const isActive = item.id === activeItemId;
          const MarkerIcon = getMarkerIcon(item.type);
          const markerColor = isActive ? 'bg-emerald-500' : getMarkerColor(item.type);

          // Dim markers from other days when a specific day is highlighted
          const isDimmed =
            highlightedDay !== null &&
            item.dayNumber !== undefined &&
            item.dayNumber !== highlightedDay;

          // Specialist POIs are slightly muted (secondary to itinerary items)
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
                {/* Pin shape */}
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

                {/* Day badge (for itinerary items) */}
                {item.dayNumber && !isActive && (
                  <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-zinc-800 border border-white/30 flex items-center justify-center">
                    <span className="text-[8px] font-bold text-white">{item.dayNumber}</span>
                  </div>
                )}

                {/* Label tooltip (only on active) */}
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
