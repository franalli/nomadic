'use client';

import { MapPin } from 'lucide-react';
import mapboxgl from 'mapbox-gl';
import { type MutableRefObject, type RefObject, useEffect } from 'react';
import type { ErrorEvent, MapRef } from 'react-map-gl/mapbox';

import { debugLog } from '@/lib/debug';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import { type MapCenter, type MapItem, normalizeMapCoordinates } from './map-marker-config';
import { isMapboxTimingError } from './mapbox-error-handler';

export const routeLayerStyle: Omit<mapboxgl.LineLayer, 'source'> = {
  id: 'route-line',
  type: 'line',
  paint: { 'line-color': DS.brand.emerald, 'line-width': 3, 'line-opacity': 0.7, 'line-dasharray': [2, 1] },
};

export const MAP_CONTAINER_STYLE = { width: '100%', height: '100%' } as const;

type MapboxTelemetryApi = typeof mapboxgl & {
  setTelemetryEnabled?: (enabled: boolean) => void;
};

(mapboxgl as MapboxTelemetryApi).setTelemetryEnabled?.(false);

export function handleMapError(event: ErrorEvent) {
  const message = event.error?.message || '';
  if (isMapboxTimingError(message)) {
    return;
  }
  debugLog('[InteractiveMap] Map error:', event.error);
}

export function getSafeDefaultCenter(defaultCenter: MapCenter): MapCenter {
  const normalized = normalizeMapCoordinates({ lat: defaultCenter.lat, lng: defaultCenter.lng });
  if (!normalized) return { lat: 0, lng: 0, zoom: 2 };
  return { lat: normalized.lat, lng: normalized.lng, zoom: defaultCenter.zoom };
}

export function normalizeMapItems(items: MapItem[]) {
  const normalizedItems: MapItem[] = [], droppedCoordinateIds: string[] = [];

  for (const item of items) {
    const coordinates = normalizeMapCoordinates(item.coordinates);
    if (!coordinates) {
      droppedCoordinateIds.push(item.id);
      continue;
    }
    normalizedItems.push({ ...item, coordinates });
  }

  return { normalizedItems, droppedCoordinateIds };
}

export function useDroppedCoordinateLogging(droppedCoordinateIds: string[]) {
  const signature = droppedCoordinateIds.join('|');

  useEffect(() => {
    if (!signature) return;
    debugLog('[InteractiveMap] Skipping items with invalid coordinates', {
      dropped_count: droppedCoordinateIds.length,
      dropped_ids: droppedCoordinateIds.slice(0, 5),
    });
  }, [droppedCoordinateIds, signature]);
}

export function useMountedFlag(isMountedRef: MutableRefObject<boolean>) {
  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, [isMountedRef]);
}

export function useAutoFitBounds({
  activeItemId,
  isDesktop,
  isMapReady,
  isMountedRef,
  mapRef,
  normalizedItems,
}: {
  activeItemId: string | null;
  isDesktop: boolean;
  isMapReady: boolean;
  isMountedRef: MutableRefObject<boolean>;
  mapRef: RefObject<MapRef | null>;
  normalizedItems: MapItem[];
}) {
  useEffect(() => {
    if (!isMapReady || !mapRef.current || !isMountedRef.current || activeItemId) return;
    if (normalizedItems.length < 2) return;
    const lngs = normalizedItems.map((item) => item.coordinates.lng);
    const lats = normalizedItems.map((item) => item.coordinates.lat);
    try {
      mapRef.current.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]], {
        padding: isDesktop ? { top: 60, bottom: 60, left: 60, right: 60 } : { top: 30, bottom: 30, left: 30, right: 30 },
        maxZoom: 14,
        minZoom: 5,
        duration: 1000,
      });
    } catch {}
  }, [activeItemId, isDesktop, isMapReady, isMountedRef, mapRef, normalizedItems]);
}

export function useActiveItemFlyTo({
  activeItemId,
  isMapReady,
  isMountedRef,
  mapRef,
  normalizedItems,
}: {
  activeItemId: string | null;
  isMapReady: boolean;
  isMountedRef: MutableRefObject<boolean>;
  mapRef: RefObject<MapRef | null>;
  normalizedItems: MapItem[];
  }) {
  useEffect(() => {
    if (!activeItemId || !isMapReady || !mapRef.current || !isMountedRef.current) return;
    const activeItem = normalizedItems.find((item) => item.id === activeItemId);
    if (!activeItem) return;
    try {
      mapRef.current.flyTo({
        center: [activeItem.coordinates.lng, activeItem.coordinates.lat],
        zoom: 9,
        pitch: 30,
        duration: 1500,
      });
    } catch {}
  }, [activeItemId, isMapReady, isMountedRef, mapRef, normalizedItems]);
}

export function useHighlightedDayFlyTo({
  highlightedDay,
  isMapReady,
  isUserInteractingRef,
  mapRef,
  normalizedItems,
}: {
  highlightedDay?: number | null;
  isMapReady: boolean;
  isUserInteractingRef: MutableRefObject<boolean>;
  mapRef: RefObject<MapRef | null>;
  normalizedItems: MapItem[];
  }) {
  useEffect(() => {
    if (highlightedDay == null || !isMapReady || !mapRef.current || isUserInteractingRef.current) return;
    const dayPins = normalizedItems.filter((item) => item.dayNumber === highlightedDay);
    if (dayPins.length === 0) return;
    const avgLat = dayPins.reduce((sum, item) => sum + item.coordinates.lat, 0) / dayPins.length;
    const avgLng = dayPins.reduce((sum, item) => sum + item.coordinates.lng, 0) / dayPins.length;
    try {
      mapRef.current.flyTo({
        center: [avgLng, avgLat],
        zoom: dayPins.length === 1 ? 9 : 7,
        duration: 1200,
        essential: true,
      });
    } catch {}
  }, [highlightedDay, isMapReady, isUserInteractingRef, mapRef, normalizedItems]);
}

export function useMapResizeObserver({
  mapContainerRef,
  mapRef,
}: { mapContainerRef: RefObject<HTMLDivElement | null>; mapRef: RefObject<MapRef | null> }) {
  useEffect(() => {
    if (!mapContainerRef.current) return;
    const observer = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    observer.observe(mapContainerRef.current);
    return () => observer.disconnect();
  }, [mapContainerRef, mapRef]);
}

export function MapTokenMissingState({ className }: { className?: string }) {
  return (
    <div className={cn('flex h-full w-full items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-zinc-900', className)}>
      <div className="p-6 text-center">
        <MapPin className="mx-auto mb-3 h-12 w-12 text-zinc-600" />
        <p className="text-sm text-zinc-400">Interactive Map</p>
        <p className="mt-1 text-xs text-zinc-500">Configure NEXT_PUBLIC_MAPBOX_TOKEN to enable</p>
      </div>
    </div>
  );
}
