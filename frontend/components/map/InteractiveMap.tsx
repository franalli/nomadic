'use client';

import 'mapbox-gl/dist/mapbox-gl.css';

import { Bed, Camera,MapPin, Mountain, Plane, Waves } from 'lucide-react';
import { useCallback,useEffect, useRef } from 'react';
import Map, { type MapRef,Marker, NavigationControl } from 'react-map-gl/mapbox';

import { cn } from '@/lib/utils';

/**
 * Map item with coordinates for marker placement
 */
export interface MapItem {
  id: string;
  title: string;
  type: string;
  coordinates: { lat: number; lng: number };
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
}

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
  if (lowerType.includes('dive') || lowerType.includes('snorkel') || lowerType.includes('water')) {
    return Waves;
  }
  if (lowerType.includes('hike') || lowerType.includes('trek') || lowerType.includes('mountain')) {
    return Mountain;
  }
  if (lowerType.includes('tour') || lowerType.includes('sightseeing')) {
    return Camera;
  }

  return MapPin;
}

/**
 * InteractiveMap
 *
 * Mapbox-powered scrollytelling map for Plan view.
 * Features:
 * - Smooth flyTo animations when active item changes
 * - 3D pitch for cinematic effect
 * - Marker scaling and highlighting for active item
 * - Dark mode styling
 */
export function InteractiveMap({
  items,
  activeItemId,
  defaultCenter,
  className,
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

  return (
    <div className={cn('w-full h-full rounded-xl overflow-hidden border border-white/10', className)}>
      <Map
        ref={mapRef}
        initialViewState={{
          longitude: defaultCenter.lng,
          latitude: defaultCenter.lat,
          zoom: defaultCenter.zoom,
        }}
        mapStyle="mapbox://styles/mapbox/dark-v11"
        mapboxAccessToken={mapboxToken}
      >
        <NavigationControl position="bottom-right" />

        {/* Render markers for all items with coordinates */}
        {items.map((item) => {
          const isActive = item.id === activeItemId;
          const MarkerIcon = getMarkerIcon(item.type);

          return (
            <Marker
              key={item.id}
              longitude={item.coordinates.lng}
              latitude={item.coordinates.lat}
              anchor="bottom"
            >
              <div
                className={cn(
                  'transition-all duration-300 transform',
                  isActive ? 'scale-125 z-50' : 'scale-100 opacity-80 hover:opacity-100'
                )}
              >
                {/* Pin shape */}
                <div
                  className={cn(
                    'flex items-center justify-center rounded-full shadow-xl border-2',
                    isActive
                      ? 'w-10 h-10 bg-orange-500 border-white'
                      : 'w-8 h-8 bg-white border-slate-200'
                  )}
                >
                  <MarkerIcon
                    className={cn(isActive ? 'text-white' : 'text-slate-800')}
                    size={isActive ? 20 : 16}
                  />
                </div>

                {/* Label tooltip (only on active) */}
                {isActive && (
                  <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 bg-black/80 backdrop-blur px-2 py-1 rounded text-[10px] text-white whitespace-nowrap">
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
