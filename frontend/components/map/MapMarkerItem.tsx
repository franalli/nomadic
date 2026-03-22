'use client';

import { Star } from 'lucide-react';
import { memo, type MutableRefObject } from 'react';
import { Marker } from 'react-map-gl/mapbox';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/state/uiStore';

import {
  formatReviewCount,
  getCategoryLabel,
  getIntensityLabel,
  getPinConfig,
  getPriceLabel,
  type MapItem,
  MARKER_Z_INDEX_STYLE,
} from './map-marker-config';

export type { MapCenter, MapItem } from './map-marker-config';
export { normalizeMapCoordinates } from './map-marker-config';
export { getPinConfig, MARKER_Z_INDEX_STYLE } from './map-marker-config';

interface MapMarkerItemProps {
  item: MapItem;
  activeItemId: string | null;
  highlightedDay?: number | null;
  onMarkerClick?: (id: string) => void;
  lastClickRef: MutableRefObject<number>;
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
  const markerBg = isActive ? DS.brand.emerald : pin.color;
  const isDimmed =
    highlightedDay != null &&
    item.dayNumber !== undefined &&
    item.dayNumber !== highlightedDay;
  const isSpecialistPoi = item.source === 'specialist';
  const isHovered = isStoreHovered;
  const showTooltip = isActive || isHovered;
  const categoryLabel = getCategoryLabel(item.type, item.source);
  const priceLabel = getPriceLabel(item.priceLevel);
  const intensityLabel = getIntensityLabel(item.intensity);
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
              ? `ring-2 ring-emerald-300/85 ${DS.glowClass.markerActive}`
              : isHovered && `ring-2 ring-emerald-400/80 ${DS.glowClass.markerHover}`,
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
