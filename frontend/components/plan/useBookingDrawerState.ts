'use client';

/**
 * useBookingDrawerState
 *
 * Manages booking drawer open/close state and the fill-day API call
 * triggered when a tile is added to a specific day via the drawer.
 */

import { useCallback, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { fillDay } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { isFillDayCooldownActive } from '@/lib/fillDayGuards';
import { useDocumentStore } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

import { type GenerationState, isGenerating } from './planStateHelpers';

interface UseBookingDrawerStateInput {
  generation?: GenerationState | null;
  isCommitting: boolean;
  isExpandingItinerary: boolean;
  onSaveTile?: (tile: Tile) => void;
}

export function useBookingDrawerState({
  generation,
  isCommitting,
  isExpandingItinerary,
  onSaveTile,
}: UseBookingDrawerStateInput) {
  const { toast } = useToast();
  const [bookingDrawerCategory, setBookingDrawerCategory] = useState<
    'hotel' | 'flight' | 'activity' | null
  >(null);
  const [bookingDrawerPinnedDay, setBookingDrawerPinnedDay] = useState<number | null>(null);
  const lastFillDayRequestAtRef = useRef(0);

  const handleOpenBookingDrawer = useCallback(
    (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => {
      setBookingDrawerCategory(category);
      setBookingDrawerPinnedDay(dayNumber ?? null);
    },
    []
  );

  const handleCloseBookingDrawer = useCallback(() => {
    setBookingDrawerCategory(null);
    setBookingDrawerPinnedDay(null);
  }, []);

  const handleSaveTile = useCallback(
    async (tile: Tile) => {
      if (bookingDrawerPinnedDay != null) {
        const store = useDocumentStore.getState();
        const generationInFlight = isGenerating(generation) || isCommitting || isExpandingItinerary;
        if (generationInFlight || store.currentRunId) {
          handleCloseBookingDrawer();
          toast('Please wait until itinerary updates complete');
          return;
        }
        const now = Date.now();
        if (isFillDayCooldownActive(now, lastFillDayRequestAtRef.current)) {
          handleCloseBookingDrawer();
          toast('Please wait a moment before adding another activity');
          return;
        }
        if (store.expandInProgress) { handleCloseBookingDrawer(); return; }
        if (!store.claimFillDay(bookingDrawerPinnedDay)) { handleCloseBookingDrawer(); return; }
        lastFillDayRequestAtRef.current = now;
        store.claimMutation();
        handleCloseBookingDrawer();
        try {
          const result = await fillDay(bookingDrawerPinnedDay, undefined, [tile.id]);
          if (result?.day_card) {
            useDocumentStore.getState().replaceDayCard(
              bookingDrawerPinnedDay, result.day_card, result.version, result.tiles
            );
          }
        } catch (err) {
          const is409 = err instanceof Error && err.message.includes('409');
          const is429 = err instanceof Error && err.message.includes('429');
          if (is409) {
            debugLog(`[fillDay] day=${bookingDrawerPinnedDay} already filled (409), refreshing card`);
            return;
          }
          if (is429) { toast('Too many requests. Please wait a moment and try again'); return; }
          console.error('[StrategyStageRenderer] fill-day failed:', err);
        } finally {
          useDocumentStore.getState().releaseMutation();
          useDocumentStore.getState().releaseFillDay(bookingDrawerPinnedDay);
        }
        return;
      }
      if (onSaveTile) { onSaveTile(tile); return; }
      const { preferredTileIds: currentPrefs, toggleTilePreference: toggle } = useDocumentStore.getState();
      if (!currentPrefs.has(tile.id)) toggle(tile.id);
    },
    [bookingDrawerPinnedDay, generation, handleCloseBookingDrawer, isCommitting, isExpandingItinerary, onSaveTile, toast]
  );

  return {
    bookingDrawerCategory,
    bookingDrawerPinnedDay,
    handleOpenBookingDrawer,
    handleCloseBookingDrawer,
    handleSaveTile,
  };
}
