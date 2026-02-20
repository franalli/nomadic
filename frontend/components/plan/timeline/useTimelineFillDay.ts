'use client';

/**
 * useTimelineFillDay
 *
 * Encapsulates fill-day state and handler logic extracted from TimelineThread.
 * Manages per-day mutex, cooldown, generation-in-flight guards, and store updates.
 */

import { useCallback, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { fillDay } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { isFillDayCooldownActive } from '@/lib/fillDayGuards';
import { showMutationToast } from '@/lib/showMutationToast';
import { useDocumentStore } from '@/state/documentStore';
import type { DayCard } from '@/types/plan-envelope';

export interface UseTimelineFillDayParams {
  disableFillDayActions: boolean;
  categories: string[] | undefined;
}

export interface UseTimelineFillDayResult {
  fillingDay: number | null;
  fillDayRejection: { dayNumber: number; reason: string } | null;
  handleFillDay: (dayNumber: number, dayDate?: string | null, chipCategories?: string[]) => Promise<void>;
}

export function useTimelineFillDay({
  disableFillDayActions,
  categories,
}: UseTimelineFillDayParams): UseTimelineFillDayResult {
  const [fillingDay, setFillingDay] = useState<number | null>(null);
  const [fillDayRejection, setFillDayRejection] = useState<{
    dayNumber: number;
    reason: string;
  } | null>(null);
  const lastFillDayRequestAtRef = useRef(0);
  const { toast } = useToast();

  const handleFillDay = useCallback(async (dayNumber: number, _dayDate?: string | null, chipCategories?: string[]) => {
    const store = useDocumentStore.getState();
    const generationInFlight = disableFillDayActions || Boolean(store.currentRunId);
    if (generationInFlight) {
      const reason = 'Please wait until itinerary updates complete';
      setFillDayRejection({ dayNumber, reason });
      toast(reason);
      return;
    }
    // Guard: skip if expand-itinerary is running (days may already be populated)
    if (store.expandInProgress) return;
    const now = Date.now();
    if (isFillDayCooldownActive(now, lastFillDayRequestAtRef.current)) {
      const reason = 'Please wait a moment before generating activities again';
      setFillDayRejection({ dayNumber, reason });
      toast(reason);
      return;
    }
    // Per-day mutex: prevents concurrent calls from any path
    if (!store.claimFillDay(dayNumber)) return;
    // Guard: skip if day already has real activity blocks (race condition with graph SSE)
    const currentDayCards = store.document?.day_cards ?? [];
    const targetCard = currentDayCards.find(dc => dc.day_number === dayNumber);
    if (targetCard) {
      const realBlocks = targetCard.blocks.filter(
        b => !b.is_buffer && b.activity_type !== 'free_day' && b.activity_type !== 'placeholder'
      );
      if (realBlocks.length > 0) {
        debugLog(`[fillDay] SKIPPED day=${dayNumber} — already has ${realBlocks.length} real blocks`);
        store.releaseFillDay(dayNumber);
        return;
      }
    }
    lastFillDayRequestAtRef.current = now;
    // Snapshot BEFORE fill (for undo)
    const snapshot = structuredClone(store.document?.day_cards ?? []) as DayCard[];
    const prevVersion = store.version;
    store.claimMutation();
    setFillingDay(dayNumber);
    setFillDayRejection(null);
    try {
      // Use chip categories from FreeDayCard; fall back to trip_inputs categories
      const effectiveCategories = chipCategories?.length ? chipCategories : (categories?.length ? categories : undefined);
      const result = await fillDay(dayNumber, effectiveCategories);
      if (result.rejected) {
        setFillDayRejection({
          dayNumber,
          reason: result.rejection_reason || 'Activity cannot be placed on this day',
        });
        return;
      }
      if (result?.day_card) {
        useDocumentStore.getState().replaceDayCard(
          dayNumber, result.day_card, result.version, result.tiles
        );
        // Set undo entry and show toast with Undo CTA
        const undoLabel = `Filled Day ${dayNumber}`;
        useDocumentStore.getState().setUndoEntry({
          type: 'fill_day',
          label: undoLabel,
          previousDayCards: snapshot,
          previousVersion: prevVersion,
          timestamp: Date.now(),
        });
        showMutationToast(undoLabel, toast);
      }
    } catch (err) {
      const is409 = err instanceof Error && err.message.includes('409');
      const is429 = err instanceof Error && err.message.includes('429');
      if (is409) {
        debugLog(`[fillDay] day=${dayNumber} already filled (409), refreshing card`);
        return;
      }
      if (is429) {
        const reason = 'Too many requests. Please wait a moment and try again';
        setFillDayRejection({ dayNumber, reason });
        toast(reason);
        return;
      }
      console.error('[TimelineThread] fill-day failed:', err);
    } finally {
      useDocumentStore.getState().releaseMutation();
      useDocumentStore.getState().releaseFillDay(dayNumber);
      setFillingDay(null);
    }
  }, [categories, disableFillDayActions, toast]);

  return { fillingDay, fillDayRejection, handleFillDay };
}
