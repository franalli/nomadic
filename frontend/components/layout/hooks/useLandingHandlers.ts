/**
 * useLandingHandlers — Event handlers for NomadicLanding.
 *
 * Consolidates reset, tile preference, gear sheets, plan generation,
 * plan result receipt, user message topic detection, build/finalize,
 * and mobile send/stop callbacks.
 */

import { useCallback, useRef, useState } from 'react';

import type { ChatPanelHandle } from '@/components/chat/ChatPanel';
import type { PlanResultPayload } from '@/components/layout/hooks/useBranchManager';
import {
  type ChangeReceiptData,
  detectChangedFieldNames,
  detectTopicsFromMessage,
  RESET_BUTTON_COOLDOWN_MS,
} from '@/components/layout/LandingHelpers';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { debugLog } from '@/lib/debug';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { Tile } from '@/types/tile';

interface UseLandingHandlersParams {
  storeReset: () => void;
  toggleTilePreference: (id: string) => void;
  storeTripInputs: DocumentTripInputs | undefined;
  closeSheet: () => void;
  mobileNavReset: () => void;
  mobileNavigateToPlan: () => void;
  navigateTo: (view: 'setup' | 'plan' | 'book') => boolean;
  finalizePlan: () => void;
  branchManagerStartNewSession: () => Promise<void>;
  handlePlanResult: (result: PlanResultPayload) => void;
  handleGeneratePlanStart: () => void;
  hasEverHadPlan: boolean;
  setHasEverHadPlan: (v: boolean) => void;
  setLocalPendingTopics: React.Dispatch<React.SetStateAction<string[]>>;
  setDestinationImageUrl: (v: string | null) => void;
  finalizeTimerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
  chatPanelRef: React.RefObject<ChatPanelHandle | null>;
  setUiGeneration: (v: null) => void;
  setUserRequestedGeneration: (v: boolean) => void;
  setChatKey: React.Dispatch<React.SetStateAction<number>>;
}

interface UseLandingHandlersReturn {
  handleStartNewSession: () => Promise<void>;
  handleSaveTilePreference: (tile: Tile) => void;
  handleOpenGearActivities: () => void;
  handleOpenGearStays: () => void;
  handleOpenGearFlights: () => void;
  handleGeneratePlanStartWithSnapshot: () => void;
  handlePlanResultWithReceipt: (result: PlanResultPayload) => void;
  handleUserMessageSubmit: (message: string) => void;
  handleBuildPlan: () => void;
  handleFinalizePlan: () => void;
  handleMobileSend: (message: string) => void;
  handleMobileStopStreaming: () => void;
  handleSendMessage: (msg: string) => void;
  isResettingSession: boolean;
  isFinalizing: boolean;
  gearActivitiesSheetOpen: boolean;
  gearStaysSheetOpen: boolean;
  gearFlightsSheetOpen: boolean;
  setGearActivitiesSheetOpen: (v: boolean) => void;
  setGearStaysSheetOpen: (v: boolean) => void;
  setGearFlightsSheetOpen: (v: boolean) => void;
  receiptDataRef: React.MutableRefObject<ChangeReceiptData | null>;
}

export function useLandingHandlers({
  storeReset,
  toggleTilePreference,
  storeTripInputs,
  closeSheet,
  mobileNavReset,
  mobileNavigateToPlan,
  navigateTo,
  finalizePlan,
  branchManagerStartNewSession,
  handlePlanResult,
  handleGeneratePlanStart,
  hasEverHadPlan,
  setHasEverHadPlan,
  setLocalPendingTopics,
  setDestinationImageUrl,
  finalizeTimerRef,
  chatPanelRef,
  setUiGeneration,
  setUserRequestedGeneration,
  setChatKey: _setChatKey,
}: UseLandingHandlersParams): UseLandingHandlersReturn {
  const isDesktop = useIsDesktop();

  const receiptDataRef = useRef<ChangeReceiptData | null>(null);
  const previousTripInputsRef = useRef<DocumentTripInputs | null>(null);
  const resetInFlightRef = useRef(false);
  const resetCooldownUntilRef = useRef(0);

  const [isResettingSession, setIsResettingSession] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [gearActivitiesSheetOpen, setGearActivitiesSheetOpen] = useState(false);
  const [gearStaysSheetOpen, setGearStaysSheetOpen] = useState(false);
  const [gearFlightsSheetOpen, setGearFlightsSheetOpen] = useState(false);

  const handleStartNewSession = useCallback(async () => {
    const now = Date.now();
    if (resetInFlightRef.current || now < resetCooldownUntilRef.current) return;
    resetInFlightRef.current = true;
    setIsResettingSession(true);
    debugLog('[handleStartNewSession] Reset triggered');
    try {
      if (finalizeTimerRef.current) {
        clearTimeout(finalizeTimerRef.current);
        finalizeTimerRef.current = null;
      }
      storeReset();
      useChatStore.getState().resetChat();
      setUiGeneration(null);
      receiptDataRef.current = null;
      previousTripInputsRef.current = null;
      setHasEverHadPlan(false);
      setUserRequestedGeneration(false);
      setLocalPendingTopics([]);
      setDestinationImageUrl(null);
      setIsFinalizing(false);
      setGearActivitiesSheetOpen(false);
      setGearStaysSheetOpen(false);
      setGearFlightsSheetOpen(false);
      closeSheet();
      if (!isDesktop) mobileNavReset();
      await branchManagerStartNewSession();
      debugLog('[handleStartNewSession] Reset complete');
    } catch (error) {
      console.error('[handleStartNewSession] Reset failed:', error);
    } finally {
      resetInFlightRef.current = false;
      resetCooldownUntilRef.current = Date.now() + RESET_BUTTON_COOLDOWN_MS;
      setIsResettingSession(false);
    }
  }, [branchManagerStartNewSession, closeSheet, finalizeTimerRef, storeReset, isDesktop, mobileNavReset, setHasEverHadPlan, setLocalPendingTopics, setDestinationImageUrl, setUiGeneration, setUserRequestedGeneration]);

  const handleSaveTilePreference = useCallback(
    (tile: Tile) => { toggleTilePreference(tile.id); },
    [toggleTilePreference]
  );
  const handleOpenGearActivities = useCallback(() => setGearActivitiesSheetOpen(true), []);
  const handleOpenGearStays = useCallback(() => setGearStaysSheetOpen(true), []);
  const handleOpenGearFlights = useCallback(() => setGearFlightsSheetOpen(true), []);

  const handleGeneratePlanStartWithSnapshot = useCallback(() => {
    previousTripInputsRef.current = storeTripInputs ? { ...storeTripInputs } : null;
    setUserRequestedGeneration(true);
    handleGeneratePlanStart();
    navigateTo('plan');
    if (!isDesktop) mobileNavigateToPlan();
  }, [storeTripInputs, handleGeneratePlanStart, navigateTo, isDesktop, mobileNavigateToPlan, setUserRequestedGeneration]);

  const handlePlanResultWithReceipt = useCallback(
    (result: PlanResultPayload) => {
      handlePlanResult(result);
      const newInputs = result.response?.document?.trip_inputs ?? null;
      const changedFields = detectChangedFieldNames(previousTripInputsRef.current, newInputs);
      if (changedFields.length > 0) {
        receiptDataRef.current = {
          type: changedFields.length === 1 ? 'partial' : 'updated',
          fields: changedFields,
          canUndo: true,
        };
      }
    },
    [handlePlanResult]
  );

  const handleUserMessageSubmit = useCallback(
    (message: string) => {
      if (!hasEverHadPlan) return;
      const detectedTopics = detectTopicsFromMessage(message);
      const existingTopics = new Set(
        useDocumentStore.getState().document?.executed_strategy_topics ?? []
      );
      const newTopics = detectedTopics.filter((t) => !existingTopics.has(t));
      if (newTopics.length > 0) {
        setLocalPendingTopics((prev) =>
          Array.from(new Map([...prev, ...newTopics].map((t) => [t, true])).keys())
        );
      }
    },
    [hasEverHadPlan, setLocalPendingTopics]
  );

  const handleBuildPlan = useCallback(() => {
    chatPanelRef.current?.sendMessage?.(GENERATE_PLAN_TRIGGER);
  }, [chatPanelRef]);

  const handleFinalizePlan = useCallback(() => {
    if (finalizeTimerRef.current) {
      clearTimeout(finalizeTimerRef.current);
      finalizeTimerRef.current = null;
    }
    setIsFinalizing(true);
    finalizeTimerRef.current = setTimeout(() => {
      finalizeTimerRef.current = null;
      finalizePlan();
      navigateTo('book');
      setIsFinalizing(false);
    }, 1500);
  }, [finalizePlan, navigateTo, finalizeTimerRef]);

  const handleMobileSend = useCallback((message: string) => {
    if (!chatPanelRef.current?.sendMessage) {
      debugLog('[MobileChatInput] ChatPanel ref not ready');
      return;
    }
    chatPanelRef.current.sendMessage(message);
  }, [chatPanelRef]);

  const handleMobileStopStreaming = useCallback(() => {
    chatPanelRef.current?.stopStreaming?.();
  }, [chatPanelRef]);

  const handleSendMessage = useCallback((msg: string) => {
    chatPanelRef.current?.sendMessage?.(msg);
  }, [chatPanelRef]);

  return {
    handleStartNewSession,
    handleSaveTilePreference,
    handleOpenGearActivities,
    handleOpenGearStays,
    handleOpenGearFlights,
    handleGeneratePlanStartWithSnapshot,
    handlePlanResultWithReceipt,
    handleUserMessageSubmit,
    handleBuildPlan,
    handleFinalizePlan,
    handleMobileSend,
    handleMobileStopStreaming,
    handleSendMessage,
    isResettingSession,
    isFinalizing,
    gearActivitiesSheetOpen,
    gearStaysSheetOpen,
    gearFlightsSheetOpen,
    setGearActivitiesSheetOpen,
    setGearStaysSheetOpen,
    setGearFlightsSheetOpen,
    receiptDataRef,
  };
}
