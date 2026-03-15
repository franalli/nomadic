'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
import {
  type KeyboardEvent,
  memo,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { TileCardContent } from '@/components/tiles/TileCardContent';
import { TileCardMedia } from '@/components/tiles/tileSections';
import { Card } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { cn, isFlightType, isHotelType } from '@/lib/utils';
import { usePreferenceActions, useTilePreference } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

import {
  getAmenityIconsWithLabels,
  getTileActivityMeta,
  getTileFeatures,
  getTileRelevanceBadges,
} from './tileHelpers';

type TileCardProps = {
  tile: Tile;
  branchId?: string;
  isSelected?: boolean;
  onToggleSelect?: (tile: Tile) => void;
  onSelectionToast?: (message: string) => void;
  isSaved?: boolean;
  onOpenStaysSettings?: () => void;
};

export const TileCard = memo(function TileCard({
  tile,
  branchId,
  isSelected,
  onToggleSelect,
  onSelectionToast,
  isSaved = false,
  onOpenStaysSettings,
}: TileCardProps) {
  const isPreferred = useTilePreference(tile.id);
  const { toggleTilePreference } = usePreferenceActions();
  const [justSelected, setJustSelected] = useState(false);
  const [heartAnimating, setHeartAnimating] = useState(false);
  useEffect(() => {
    if (!heartAnimating) return;
    const timer = setTimeout(() => setHeartAnimating(false), 200);
    return () => clearTimeout(timer);
  }, [heartAnimating]);
  const prevSelectedRef = useRef(isSelected);
  const trackAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => { trackAbortRef.current?.abort(); };
  }, []);

  const features = useMemo(() => getTileFeatures(tile), [tile]);
  const relevanceBadges = useMemo(() => getTileRelevanceBadges(tile), [tile]);
  const amenityIcons = useMemo(() => getAmenityIconsWithLabels(tile), [tile]);
  const activityMeta = useMemo(() => getTileActivityMeta(tile), [tile]);
  const isFlight = isFlightType(tile.type || '');
  const isHotel = isHotelType(tile.type || '');

  useEffect(() => {
    if (isSelected && !prevSelectedRef.current) {
      setJustSelected(true);
      const timer = setTimeout(() => setJustSelected(false), 300);
      return () => clearTimeout(timer);
    }
    prevSelectedRef.current = isSelected;
    return undefined;
  }, [isSelected]);

  const trackClick = useCallback(() => {
    trackAbortRef.current?.abort();
    const controller = new AbortController();
    trackAbortRef.current = controller;

    apiFetch('/api/tiles/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tile_id: tile.id,
        branch_id: branchId ?? null,
        user_id: null,
      }),
      signal: controller.signal,
    }).catch((error) => {
      if (error instanceof Error && error.name === 'AbortError') return;
      if (process.env.NODE_ENV !== 'production') {
        debugLog('Click tracking failed:', error);
      }
    });
  }, [tile.id, branchId]);

  const handleClick = useCallback(() => {
    trackClick();
    window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer');
  }, [trackClick, tile.deeplink_url]);

  const handleToggleSelect = useCallback(
    (event: MouseEvent | KeyboardEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();

      if (!isSelected && onSelectionToast) {
        const displayTitle = tile.title.length > 30 ? tile.title.slice(0, 27) + '...' : tile.title;
        onSelectionToast(`Added ${displayTitle} to your trip`);
      }

      onToggleSelect?.(tile);
    },
    [onToggleSelect, tile, isSelected, onSelectionToast]
  );

  const handlePreferenceToggle = useCallback((event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    debugLog('[TileCard] 💜 Heart clicked for tile:', tile.id);
    setHeartAnimating(true);
    toggleTilePreference(tile.id);
  }, [toggleTilePreference, tile.id]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Enter' || event.key === ' ') {
        handleToggleSelect(event);
      }
    },
    [handleToggleSelect]
  );

  const handleViewDetailsClick = useCallback(
    (event: MouseEvent) => {
      event.stopPropagation();
      handleClick();
    },
    [handleClick]
  );

  return (
    <Card
      data-tile-id={tile.id}
      onClick={handleToggleSelect}
      className={cn(
        'bg-white dark:bg-zinc-900 group relative flex h-full flex-col overflow-hidden rounded-2xl border shadow-card transition-all hover:shadow-soft',
        isSelected
          ? 'ring-2 ring-emerald-500 border-emerald-500'
          : 'border-zinc-200 dark:border-white/10',
        justSelected && 'scale-[1.02]',
        'transition-transform duration-200 ease-out'
      )}
      role="button"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <TileCardMedia
        tile={tile}
        isFlight={isFlight}
        isPreferred={isPreferred}
        isSaved={isSaved}
        heartAnimating={heartAnimating}
        onPreferenceToggle={handlePreferenceToggle}
        onOpenStaysSettings={onOpenStaysSettings}
      />

      <TileCardContent
        tile={tile}
        isHotel={isHotel}
        activityMeta={activityMeta}
        amenityIcons={amenityIcons}
        relevanceBadges={relevanceBadges}
        features={features}
        onViewDetailsClick={handleViewDetailsClick}
      />
    </Card>
  );
});
