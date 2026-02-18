'use client';

// date-fns imports removed - no longer needed after TripDetailsForm removal
import { Compass, Loader2, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { StartupSequence } from '@/components/animations/StartupSequence';
import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { MobileChatInput } from '@/components/chat/MobileChatInput';
import { TripStatusBar } from '@/components/chat/TripStatusBar';
import { FloatingBuildButton } from '@/components/layout/FloatingBuildButton';
import {
  type PlanResultPayload,
  useBranchManager,
} from '@/components/layout/hooks/useBranchManager';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { isBootstrap, isFraming, isStrategyReady, shouldAutoTriggerItinerary } from '@/components/plan/planStateHelpers';
import { ActivitiesSheet } from '@/components/plan/sheets/ActivitiesSheet';
import { BudgetSheet } from '@/components/plan/sheets/BudgetSheet';
import { DatesSheet } from '@/components/plan/sheets/DatesSheet';
import { DestinationSheet } from '@/components/plan/sheets/DestinationSheet';
import { FlightsSheet } from '@/components/plan/sheets/FlightsSheet';
import { OriginSheet } from '@/components/plan/sheets/OriginSheet';
import { StaysSheet } from '@/components/plan/sheets/StaysSheet';
import { TravelersSheet } from '@/components/plan/sheets/TravelersSheet';
import { TripSettingsSheet } from '@/components/plan/sheets/TripSettingsSheet';
import { StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { Button } from '@/components/ui/button';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { usePreferenceAutoRegen } from '@/hooks/usePreferenceAutoRegen';
import { useSheetManager } from '@/hooks/useSheetManager';
import { useSpecialistDeepLink } from '@/hooks/useSpecialistDeepLink';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { apiFetch, fetchDestinationImage } from '@/lib/api';
import { parseISODateLocal } from '@/lib/date-utils';
import { debugLog } from '@/lib/debug';
import { DS } from '@/lib/design-system';
import type { SpecialistType } from '@/lib/specialistLinkParser';
import { consumeNdjsonEnvelopeStream } from '@/lib/streamParser';
import { formatDateForDisplay } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import type { DocumentTripInputs, PlanDocumentData } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanState, PlanViewModel, PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

// Receipt data type for showing "Updated: X, Y · Undo" after freeform extraction
interface ChangeReceiptData {
  type: 'partial' | 'updated' | 'reverted';
  fields: string[];
  canUndo: boolean;
}

// Topic keywords for detecting specialist topics from user messages
// Matches backend orchestrator.py TOPIC_KEYWORDS
const TOPIC_KEYWORDS: Record<string, string[]> = {
  diving: ['dive', 'diving', 'scuba', 'snorkel', 'reef'],
  hiking: ['hike', 'hiking', 'trek', 'trail', 'mountain'],
  skiing: ['ski', 'skiing', 'snowboard', 'piste'],
  cycling: ['bike', 'cycling', 'bicycle'],
  boating: ['sail', 'boat', 'yacht', 'kayak'],
};

const RESET_BUTTON_COOLDOWN_MS = 2500;

/**
 * Detect specialist topics from user message text.
 * Used for optimistic UI - shows placeholder AgentCards before backend responds.
 */
function detectTopicsFromMessage(message: string): string[] {
  const lower = message.toLowerCase();
  return Object.entries(TOPIC_KEYWORDS)
    .filter(([, keywords]) => keywords.some((k) => lower.includes(k)))
    .map(([topic]) => topic);
}

// Toast notification system

// Helper to detect which trip input fields changed between two states
function detectChangedFieldNames(
  oldInputs: DocumentTripInputs | null,
  newInputs: DocumentTripInputs | null
): string[] {
  if (!newInputs) return [];

  const changed: string[] = [];

  // Compare core fields
  if (oldInputs?.origin !== newInputs.origin && newInputs.origin) {
    changed.push('origin');
  }
  if (oldInputs?.destination !== newInputs.destination && newInputs.destination) {
    changed.push('destination');
  }
  if (oldInputs?.start_date !== newInputs.start_date && newInputs.start_date) {
    changed.push('start_date');
  }
  if (oldInputs?.end_date !== newInputs.end_date && newInputs.end_date) {
    changed.push('end_date');
  }
  if (oldInputs?.budget !== newInputs.budget && newInputs.budget != null) {
    changed.push('budget');
  }
  if (oldInputs?.adults !== newInputs.adults && newInputs.adults != null) {
    changed.push('adults');
  }
  if (oldInputs?.children !== newInputs.children && newInputs.children != null) {
    changed.push('children');
  }

  return changed;
}

export function NomadicLanding() {
  // Viewport detection
  const isDesktop = useIsDesktop();
  // Mobile page navigation (Chat ↔ Plan swipe)
  const { mobileNavigateToPlan, mobileNavReset, mobileSetHasNewContent } =
    useMobileNavStore(
      useShallow((s) => ({
        mobileNavigateToPlan: s.navigateToPlan,
        mobileNavReset: s.reset,
        mobileSetHasNewContent: s.setHasNewPlanContent,
      }))
    );

  // Document store - single source of truth for trip inputs + plan envelope
  // Split into focused selectors by render concern to reduce unnecessary re-renders

  // Actions (stable references, rarely change)
  const {
    setActiveView,
    storeReset,
    storeStartGeneration,
    storeIsCurrentRun,
    storeMergeEnvelope,
    storeMarkPreferencesAsApplied,
    storeCompleteGeneration,
    storeCommitTripInputs,
    storeUpdateTripInputs,
    toggleTilePreference,
  } = useDocumentStore(
    useShallow((s) => ({
      setActiveView: s.setActiveView,
      storeReset: s.reset,
      storeStartGeneration: s.startGeneration,
      storeIsCurrentRun: s.isCurrentRun,
      storeMergeEnvelope: s.mergeEnvelope,
      storeMarkPreferencesAsApplied: s.markPreferencesAsApplied,
      storeCompleteGeneration: s.completeGeneration,
      storeCommitTripInputs: s.commitTripInputs,
      storeUpdateTripInputs: s.updateTripInputs,
      toggleTilePreference: s.toggleTilePreference,
    }))
  );

  // Trip inputs + commit state
  const { storeTripInputs, isCommitting } = useDocumentStore(
    useShallow((s) => ({
      storeTripInputs: s.document?.trip_inputs,
      isCommitting: s.isCommitting,
    }))
  );

  // Plan document data (for rendering)
  const {
    docPlanState,
    docDestinationCard,
    docPlanViewState,
    docStrategySections,
    docTiles,
    docExecutedTopics,
    docPendingTopics,
    docDayCards,
    docGeneration,
    docOpenDecisions,
    docItineraryOverview,
    docItineraryAssumptions,
    docNeedsRefresh,
    docCanExpand,
    preferredTileIds,
  } = useDocumentStore(
    useShallow((s) => ({
      docPlanState: s.document?.plan_state,
      docDestinationCard: s.document?.destination_card,
      docPlanViewState: s.document?.plan_view_state,
      docStrategySections: s.document?.strategy_sections,
      docTiles: s.document?.tiles,
      docExecutedTopics: s.document?.executed_strategy_topics,
      docPendingTopics: s.document?.pending_strategy_topics,
      docDayCards: s.document?.day_cards,
      docGeneration: s.generation,
      docOpenDecisions: s.document?.open_decisions,
      docItineraryOverview: s.document?.itinerary_overview,
      docItineraryAssumptions: s.document?.itinerary_assumptions,
      docNeedsRefresh: s.document?.needs_refresh,
      docCanExpand: s.document?.can_expand_to_itinerary,
      preferredTileIds: s.preferredTileIds,
    }))
  );

  // Sheet manager - shared between header pills and chat panel
  // In S1+, header pills are the only interactive surface for trip inputs
  const { activeSheet, openSheet, closeSheet } = useSheetManager();

  // View navigation - decoupled from plan_view_state
  const {
    navigateTo,
    finalizePlan,
    canViewPlan,
    activeView,
  } = useViewNavigation();

  // ChatPanel ref - defined early so regeneration can trigger via it
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);

  // Preference auto-regen - instant regeneration when hearts change
  usePreferenceAutoRegen();

  // Receipt state - shows "Updated: X, Y · Undo" after freeform extraction
  // Kept for future receipt UI implementation
  const [, setReceiptData] = useState<ChangeReceiptData | null>(null);
  const previousTripInputsRef = useRef<DocumentTripInputs | null>(null);

  // Track if we've ever had a plan to prevent regression to Setup mode
  // Once a plan is generated, we stay in Plan mode (never revert to S0_BOOTSTRAP)
  // Using state (not ref) so changes trigger re-renders and useMemo re-computation
  const [hasEverHadPlan, setHasEverHadPlan] = useState(false);

  // Track if user explicitly requested plan generation (clicked "Build Plan")
  // This prevents Plan tab from showing prematurely when backend sends data
  const [userRequestedGeneration, setUserRequestedGeneration] = useState(false);

  // Track if plan finalization is in progress (for "Scanning best rates..." UI)
  const [isFinalizing, setIsFinalizing] = useState(false);

  // Optimistic pending topics - detected from user messages before backend responds
  // Used to show placeholder AgentCards immediately while backend processes
  const [localPendingTopics, setLocalPendingTopics] = useState<string[]>([]);

  // Activity settings sheet - opened from gear icons on specialist cards
  const [gearActivitiesSheetOpen, setGearActivitiesSheetOpen] = useState(false);

  // Stays settings sheet - opened from gear icons on hotel/check-in blocks
  const [gearStaysSheetOpen, setGearStaysSheetOpen] = useState(false);

  // Flights settings sheet - opened from gear icons on flight blocks
  const [gearFlightsSheetOpen, setGearFlightsSheetOpen] = useState(false);

  // Derive tripInputs from store (with defaults)
  const tripInputs: DocumentTripInputs = useMemo(() => {
    if (!storeTripInputs) return DEFAULT_TRIP_INPUTS;
    return { ...DEFAULT_TRIP_INPUTS, ...storeTripInputs };
  }, [storeTripInputs]);

  // Toast system - use centralized ToastProvider
  const { toast } = useToast();

  // Wrapper for legacy addToast signature (message, type) -> toast(message, { type })
  // Maps 'confirmation' type to 'success' since ToastProvider only supports standard types
  const addToast = useCallback(
    (message: string, type: ToastType = 'info') => {
      // Map legacy 'confirmation' type to 'success' for the unified toast system
      const mappedType = type === 'confirmation' ? 'success' : type;
      toast(message, { type: mappedType as 'success' | 'info' | 'warning' | 'error' });
    },
    [toast]
  );

  // Local UI generation state (fallback if backend doesn't emit generation in envelope)
  const [uiGeneration, setUiGeneration] = useState<GenerationState | null>(null);

  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);
  const [isResettingSession, setIsResettingSession] = useState(false);
  const resetInFlightRef = useRef(false);
  const resetCooldownUntilRef = useRef(0);

  // Use hook for local booking settings state management
  const {
    bookingTypes,
    flightSettings,
    hotelSettings,
    activitySettings,
    handleUpdateBookingTypes,
    handleUpdateFlightSettings,
    handleUpdateHotelSettings,
    handleUpdateActivitySettings,
  } = useLocalBookingSettings(storeTripInputs, addToast);

  // Destination image state - fetched from Unsplash when destination changes
  const [destinationImageUrl, setDestinationImageUrl] = useState<string | null>(null);
  const lastFetchedDestination = useRef<string | null>(null);

  // Fetch destination image when destination changes (with AbortController)
  useEffect(() => {
    const destination = tripInputs.destination;
    if (!destination || destination === lastFetchedDestination.current) return;

    lastFetchedDestination.current = destination;
    setDestinationImageUrl(null); // Clear while loading

    const controller = new AbortController();

    fetchDestinationImage(destination, { signal: controller.signal })
      .then((res) => {
        // Only update if not aborted and this is still the current destination
        if (
          !controller.signal.aborted &&
          lastFetchedDestination.current === destination
        ) {
          setDestinationImageUrl(res.image_url);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          console.error('Failed to fetch destination image:', err);
        }
      });

    return () => controller.abort();
  }, [tripInputs.destination]);

  // Branch manager hook - manages branches, tiles, and generating state
  const branchManager = useBranchManager({
    chatPanelContainerRef,
    onToast: addToast,
    onChatKeyIncrement: useCallback(() => setChatKey((prev) => prev + 1), []),
    resetDraft: () => tripInputsEditorRef.current?.resetDraft(),
  });

  // Keep a ref to tripInputsEditor for the branchManager resetDraft callback
  const tripInputsEditorRef = useRef<ReturnType<typeof useTripInputsEditor> | null>(null);

  // Destructure commonly used values from the branch manager hook
  const {
    selectedBranchId,
    isGenerating,
    isRegenerating,
    readyToGenerate,
    hasBranchesReady,
    handleStartNewSession: branchManagerStartNewSession,
    handlePlanResult,
    handleGeneratePlanStart,
  } = branchManager;

  // Wrap handleStartNewSession to also clear all local state
  const handleStartNewSession = useCallback(async () => {
    const now = Date.now();
    if (resetInFlightRef.current || now < resetCooldownUntilRef.current) {
      return;
    }
    resetInFlightRef.current = true;
    setIsResettingSession(true);
    debugLog('[handleStartNewSession] 🔄 Reset triggered');
    try {
      // CRITICAL: Reset document store FIRST (synchronously) to prevent stale state
      // from causing incorrect planViewState computation during async operations
      storeReset();
      // Reset chat store synchronously so empty state ("Where to next?") shows
      // immediately — don't wait for async branchManagerStartNewSession network calls
      useChatStore.getState().resetChat();
      debugLog(
        '[handleStartNewSession] ✅ documentStore.reset() + chatStore.resetChat() done'
      );
      // Clear local UI generation state
      setUiGeneration(null);
      // Clear receipt data
      setReceiptData(null);
      previousTripInputsRef.current = null;
      // Reset plan history flag - allows returning to S0_BOOTSTRAP
      setHasEverHadPlan(false);
      // Reset user generation request flag - critical for returning to Setup
      setUserRequestedGeneration(false);
      // Clear optimistic pending topics
      setLocalPendingTopics([]);
      // Clear destination image
      setDestinationImageUrl(null);
      lastFetchedDestination.current = null;
      // Reset finalization state
      setIsFinalizing(false);
      // Close gear settings sheets
      setGearActivitiesSheetOpen(false);
      setGearStaysSheetOpen(false);
      setGearFlightsSheetOpen(false);
      // Close any open trip input sheet
      closeSheet();
      // Reset mobile nav to chat page
      if (!isDesktop) {
        mobileNavReset();
      }
      // Proceed with branch manager reset (clears server session, chat, branches, etc.)
      debugLog('[handleStartNewSession] ⏳ Calling branchManagerStartNewSession...');
      await branchManagerStartNewSession();
      debugLog('[handleStartNewSession] ✅ Reset complete');
    } catch (error) {
      console.error('[handleStartNewSession] ❌ Reset failed:', error);
    } finally {
      resetInFlightRef.current = false;
      resetCooldownUntilRef.current = Date.now() + RESET_BUTTON_COOLDOWN_MS;
      setIsResettingSession(false);
    }
  }, [
    branchManagerStartNewSession,
    closeSheet,
    storeReset,
    isDesktop,
    mobileNavReset,
  ]);

  const handleSaveTilePreference = useCallback(
    (tile: Tile) => {
      toggleTilePreference(tile.id);
    },
    [toggleTilePreference]
  );
  const handleOpenGearActivities = useCallback(() => setGearActivitiesSheetOpen(true), []);
  const handleOpenGearStays = useCallback(() => setGearStaysSheetOpen(true), []);
  const handleOpenGearFlights = useCallback(() => setGearFlightsSheetOpen(true), []);

  // Wrapped handlers for receipt functionality
  // Snapshot trip inputs before generation starts + switch to Plan Mode on mobile
  const handleGeneratePlanStartWithSnapshot = useCallback(() => {
    previousTripInputsRef.current = storeTripInputs ? { ...storeTripInputs } : null;
    setUserRequestedGeneration(true); // Track explicit user request for Plan tab
    handleGeneratePlanStart();
    // Navigate to Plan view when generation starts
    navigateTo('plan');
    // Auto-navigate to plan page on mobile when generation starts
    if (!isDesktop) {
      mobileNavigateToPlan();
    }
  }, [
    storeTripInputs,
    handleGeneratePlanStart,
    navigateTo,
    isDesktop,
    mobileNavigateToPlan,
  ]);

  // Compare inputs after plan result and show receipt
  const handlePlanResultWithReceipt = useCallback(
    (result: PlanResultPayload) => {
      handlePlanResult(result);

      // Compute what changed for receipt
      const newInputs = result.response?.document?.trip_inputs ?? null;
      const changedFields = detectChangedFieldNames(
        previousTripInputsRef.current,
        newInputs
      );

      if (changedFields.length > 0) {
        setReceiptData({
          type: changedFields.length === 1 ? 'partial' : 'updated',
          fields: changedFields,
          canUndo: true,
        });
      }
    },
    [handlePlanResult]
  );

  // Handle user message submission for optimistic topic detection
  // Detects specialist topics from message and adds placeholder AgentCards immediately
  const handleUserMessageSubmit = useCallback(
    (message: string) => {
      if (!hasEverHadPlan) return; // Only do optimistic UI after first plan

      const detectedTopics = detectTopicsFromMessage(message);
      // Use getState() to avoid stale closure + full-store subscription
      const existingTopics = new Set(
        useDocumentStore.getState().document?.executed_strategy_topics ?? []
      );
      const newTopics = detectedTopics.filter((t) => !existingTopics.has(t));

      if (newTopics.length > 0) {
        setLocalPendingTopics((prev) => {
          // Stable deduplication using Map
          return Array.from(
            new Map([...prev, ...newTopics].map((t) => [t, true])).keys()
          );
        });
      }
    },
    [hasEverHadPlan]
  );

  // Receipt undo/dismiss handlers removed - re-add when receipt UI is implemented
  // Uses: previousTripInputsRef, storeTripInputs, setReceiptData, detectChangedFieldNames

  // Trip inputs editor hook - manages all trip input editing state and handlers
  const tripInputsEditor = useTripInputsEditor({
    tripInputs,
    storeTripInputs,
    onToast: addToast,
  });

  // Update ref after tripInputsEditor is created (must be in useEffect, not during render)
  useEffect(() => {
    tripInputsEditorRef.current = tripInputsEditor;
  }, [tripInputsEditor]);

  const missingFields = tripInputs.missing_fields ?? [];

  // Check if we have origin or destination to show route
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination = Boolean(tripInputs.destination);
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);

  // NEW: Derive plan state envelope fields
  // Use backend-provided plan_state if available, otherwise derive from local state

  const documentPlanState = docPlanState;
  const planState: PlanState = useMemo(() => {
    if (documentPlanState) return documentPlanState;
    // Fallback: derive from local state
    if (isGenerating) return 'RESOLVING';
    if (missingFields.length > 0 || !hasOrigin || !hasDestination || !hasStartDate) {
      return 'INCOMPLETE';
    }
    return 'STABLE';
  }, [
    documentPlanState,
    isGenerating,
    missingFields.length,
    hasOrigin,
    hasDestination,
    hasStartDate,
  ]);

  // Readiness and resolver state - kept for future use when backend provides these fields
  // These will power a visual progress indicator in the planner panel

  // Destination card (from backend or derive locally)
  // Use route-derived subtitle: "Origin → Destination · Date"
  // Include fetched destination image URL for immediate display
  const destinationCard = hasDestination
    ? {
        ...(docDestinationCard ?? {
          title: tripInputs.destination ?? '',
          subtitle: (() => {
            const parts: string[] = [];
            // Add origin → destination if we have origin
            if (tripInputs.origin) {
              parts.push(`${tripInputs.origin} → ${tripInputs.destination ?? ''}`);
            }
            // Add date if available
            if (tripInputs.start_date) {
              // Format date nicely (e.g., "Jan 21")
              const date = parseISODateLocal(tripInputs.start_date);
              if (date) {
                const formatted = date.toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                });
                parts.push(formatted);
              }
            }
            // Return route-derived subtitle or fallback
            return parts.length > 0
              ? parts.join(' · ')
              : `Trip to ${tripInputs.destination ?? ''}`;
          })(),
        }),
        // Prefer freshly fetched async destination image over persisted doc value.
        image_url: destinationImageUrl ?? docDestinationCard?.image_url ?? undefined,
      }
    : undefined;

  // Booking status (from backend, for per-tab display) - kept for future booking UI

  // Plan View State (for StrategyStageRenderer)
  // Use backend's plan_view_state if available, otherwise derive locally
  const backendPlanViewState = docPlanViewState;
  const hasStrategyContent = (docStrategySections?.length ?? 0) > 0;

  // Update hasEverHadPlan when plan content becomes available
  // Tiles indicate plan is ready
  // Using state ensures useMemo re-computes when this changes
  const docTileCount = useMemo(() => Object.keys(docTiles ?? {}).length, [docTiles]);
  const hasTilesReady = docTileCount > 0;
  const hasDayCardsReady = (docDayCards?.length ?? 0) > 0;
  useEffect(() => {
    // Legacy path: branches + strategy
    if (
      hasBranchesReady &&
      hasStrategyContent &&
      !hasEverHadPlan &&
      userRequestedGeneration
    ) {
      setHasEverHadPlan(true);
    }
    // Tiles path: tiles exist (even without explicit Build Plan click)
    if (hasTilesReady && !hasEverHadPlan) {
      setHasEverHadPlan(true);
    }
    // Day cards path: itinerary was previously built (e.g., hydration from DB)
    if (hasDayCardsReady && !hasEverHadPlan) {
      setHasEverHadPlan(true);
    }
  }, [
    hasBranchesReady,
    hasStrategyContent,
    hasEverHadPlan,
    userRequestedGeneration,
    hasTilesReady,
    hasDayCardsReady,
  ]);

  // Clear local pending topics when backend responds with executed_strategy_topics
  // Topics that appear in executed are successfully processed
  // Topics that were pending but didn't execute stay (backend didn't process them)
  const executedTopics = useMemo(() => docExecutedTopics ?? [], [docExecutedTopics]);
  useEffect(() => {
    if (executedTopics.length > 0) {
      setLocalPendingTopics((prev) =>
        prev.filter((topic) => !executedTopics.includes(topic))
      );
    }
  }, [executedTopics]);

  // Badge notification: Track when specialists update (for Plan tab badge on mobile)
  // Track executed topics for toast notifications
  // @see docs/ux_unified_architecture.md Section X - Mobile Toast Notifications
  const lastSeenTopicsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const executed = new Set(executedTopics);
    const newTopics = [...executed].filter((t) => !lastSeenTopicsRef.current.has(t));
    const hasNew = newTopics.length > 0;
    // Show toast when new topics executed
    if (hasNew) {
      const topicLabel = newTopics[0].charAt(0).toUpperCase() + newTopics[0].slice(1);
      toast(`Plan Updated: ${topicLabel} Strategy Added`);
      lastSeenTopicsRef.current = executed;
    }
  }, [executedTopics, toast]);

  const planViewState: PlanViewState = useMemo(() => {
    // =========================================================================
    // Setup → Plan transition logic
    // =========================================================================
    // Auto-transitions when tiles are available

    // Fast path: If plan content exists (tiles OR day_cards), trust backend's plan_view_state
    // After hydration reconciliation in fetchDocument(), backendPlanViewState is already corrected
    if (
      (hasTilesReady || hasDayCardsReady) &&
      backendPlanViewState &&
      backendPlanViewState !== 'S0_BOOTSTRAP'
    ) {
      return backendPlanViewState;
    }

    // Before user clicks "Build Plan", stay in Setup mode
    // CRITICAL FIX: Trust backend's S2_STRATEGY_READY when strategy content exists
    // This fixes the "diving in Bali" case where specialist runs via chat without "Build Plan"
    // @see docs/ux_unified_architecture.md - Strategy content should trigger Plan view
    if (!hasEverHadPlan && !userRequestedGeneration && !hasTilesReady) {
      // If backend says S2_STRATEGY_READY AND we have strategy content, trust it
      if (backendPlanViewState === 'S2_STRATEGY_READY' && hasStrategyContent) {
        return 'S2_STRATEGY_READY';
      }
      return 'S0_BOOTSTRAP';
    }

    // During generation, show loading state
    if (isGenerating && userRequestedGeneration) return 'S1_FRAMING';

    // CRITICAL: Check hasEverHadPlan BEFORE backend state
    // This prevents regression to S0_BOOTSTRAP when backend sends stale state
    if (hasEverHadPlan) {
      // Backend can still override for valid transitions (RESOLVING, S1_FRAMING, etc.)
      // But we block S0_BOOTSTRAP specifically
      if (backendPlanViewState && backendPlanViewState !== 'S0_BOOTSTRAP') {
        return backendPlanViewState;
      }
      // Stay in Plan mode - show strategy content or tiles
      if (hasTilesReady) return 'S2_STRATEGY_READY';
      return hasStrategyContent ? 'S2_STRATEGY_READY' : 'S2_BLOCKED';
    }

    // User requested generation but plan not ready yet - show loading
    if (userRequestedGeneration) {
      if (backendPlanViewState && backendPlanViewState !== 'S0_BOOTSTRAP') {
        return backendPlanViewState;
      }
      return 'S1_FRAMING';
    }

    return 'S0_BOOTSTRAP';
  }, [
    backendPlanViewState,
    isGenerating,
    hasStrategyContent,
    hasEverHadPlan,
    userRequestedGeneration,
    hasTilesReady,
    hasDayCardsReady,
  ]);

  // Auto-switch to Plan view when generation is in progress
  useEffect(() => {
    if (isFraming(planViewState)) {
      if (!isDesktop) {
        mobileNavigateToPlan(); // Auto-swipe to plan page
      }
      // Desktop: Update activeView in store
      setActiveView('planning');
    }
  }, [isDesktop, planViewState, mobileNavigateToPlan, setActiveView]);

  // Mobile badge: plan content updated while user is on chat page
  const mobileActivePage = useMobileNavStore((s) => s.activePage);
  const tileCount = docTileCount;
  const prevTileCountRef = useRef(0);
  useEffect(() => {
    if (!isDesktop && mobileActivePage === 0 && tileCount > prevTileCountRef.current) {
      mobileSetHasNewContent(true);
    }
    prevTileCountRef.current = tileCount;
  }, [isDesktop, mobileActivePage, tileCount, mobileSetHasNewContent]);

  // Specialist deep link navigation - handles clicks on specialist mentions in chat
  const { navigateToSpecialist } = useSpecialistDeepLink();
  useEffect(() => {
    const handleSpecialistNavigate = (event: Event) => {
      const customEvent = event as CustomEvent<{ specialistType: string }>;
      navigateToSpecialist(customEvent.detail.specialistType as SpecialistType);
    };
    window.addEventListener('specialist-navigate', handleSpecialistNavigate);
    return () => {
      window.removeEventListener('specialist-navigate', handleSpecialistNavigate);
    };
  }, [navigateToSpecialist]);

  // Merge pending topics: backend + local optimistic (stable ordering via Map)
  const mergedPendingTopics = useMemo(() => {
    const backendPending = docPendingTopics ?? [];
    // Use Map for stable deduplication (like Python's dict.fromkeys)
    return Array.from(
      new Map([...backendPending, ...localPendingTopics].map((t) => [t, true])).keys()
    );
  }, [docPendingTopics, localPendingTopics]);

  // Plan View Model - populated from backend response via granular selectors
  // PERF: Granular deps prevent recompute when unrelated fields change
  const planViewModel: PlanViewModel = useMemo(() => {
    return {
      strategy_sections: docStrategySections,
      executed_strategy_topics: docExecutedTopics,
      pending_strategy_topics: mergedPendingTopics,
      open_decisions: docOpenDecisions ?? [],
      itinerary_overview: docItineraryOverview ?? undefined,
      day_cards: docDayCards,
      itinerary_assumptions: docItineraryAssumptions ?? undefined,
      needs_refresh: docNeedsRefresh,
      can_expand_to_itinerary: docCanExpand,
    };
  }, [
    docStrategySections,
    docExecutedTopics,
    mergedPendingTopics,
    docOpenDecisions,
    docItineraryOverview,
    docDayCards,
    docItineraryAssumptions,
    docNeedsRefresh,
    docCanExpand,
  ]);

  // Merged generation state: envelope wins if present, else local UI fallback
  const envelopeGeneration = docGeneration as GenerationState | undefined;
  const generation: GenerationState | null = useMemo(() => {
    if (envelopeGeneration) return envelopeGeneration;
    if (uiGeneration) return uiGeneration;
    // Derive from isGenerating flag when no explicit generation state
    if (isGenerating) return { active: true, stage: 'structure' as const };
    return null;
  }, [envelopeGeneration, uiGeneration, isGenerating]);

  // Tiles from document store
  const tiles = useMemo(() => docTiles ?? {}, [docTiles]);

  // Plan tab enabled when we have branches/plan content (unlocked after Build)
  const planTabEnabled = useMemo(() => {
    // Plan is available if we have branches or are past S0
    return hasBranchesReady || !isBootstrap(planViewState);
  }, [hasBranchesReady, planViewState]);

  // Fallback title from tripInputs (used when destinationCard not yet available)
  const fallbackTitle = tripInputs.destination ?? undefined;

  // CTA gating flags per strict render contract
  // hasDates: BOTH start_date AND end_date required for fixed trips
  // OR flexible dates with duration
  const hasDates =
    (Boolean(tripInputs.start_date) && Boolean(tripInputs.end_date)) ||
    (tripInputs.date_flex === true && tripInputs.trip_duration != null);
  const canGeneratePlan = hasDestination && hasDates;
  const hasPlan = hasBranchesReady;

  // AUTO-TRANSITION: Switch to Plan when dates are set (SOFT GATE)
  // @see docs/ux_unified_architecture.md Section VI - "Dates = Search Trigger"
  // When user provides dates, auto-navigate to Plan view to show loading/results
  useEffect(() => {
    // Only auto-switch if:
    // 1. Dates are set (hasDates = true)
    // 2. Plan view is accessible (canViewPlan = true)
    // 3. Currently in Setup view
    if (hasDates && canViewPlan && activeView === 'setup') {
      if (!isDesktop) {
        mobileSetHasNewContent(true); // Badge the plan tab
      }
      setActiveView('planning');
    }
  }, [
    hasDates,
    canViewPlan,
    activeView,
    isDesktop,
    mobileSetHasNewContent,
    setActiveView,
  ]);

  // ─────────────────────────────────────────────────────────────────────────────
  // Itinerary Generation Flow
  // ─────────────────────────────────────────────────────────────────────────────

  // Timezone-safe date addition utility
  const addDaysUTC = useCallback((isoDate: string, days: number): string => {
    const [y, m, d] = isoDate.split('-').map(Number);
    const dateUTC = new Date(Date.UTC(y, m - 1, d));
    dateUTC.setUTCDate(dateUTC.getUTCDate() + days);
    return dateUTC.toISOString().slice(0, 10);
  }, []);

  // Actual itinerary generation logic - accepts optional override to avoid state race
  const STREAM_TIMEOUT_MS = 30000;
  const proceedWithItineraryGeneration = useCallback(
    async (options?: { forceFullRebuild?: boolean }) => {
      // RACE GUARD: Check if generation is already in progress via store
      // (checking store directly avoids stale closure issues)
      const existingRunId = useDocumentStore.getState().currentRunId;
      if (existingRunId) {
        debugLog(
          '[proceedWithItineraryGeneration] ⏭️ Skipped - generation already registered:',
          existingRunId
        );
        return;
      }

      // RACE GUARD: Check if expand is already in progress (prevents cascade)
      if (useDocumentStore.getState().expandInProgress) {
        debugLog(
          '[proceedWithItineraryGeneration] ⏭️ Skipped - expandInProgress flag set'
        );
        return;
      }

      // Generate runId for this generation (also serves as idempotency key)
      const runId = crypto.randomUUID();

      // Start generation in documentStore - gets AbortController and registers runId
      // ATOMIC: startGeneration returns null if another generation is already running
      const abortController = storeStartGeneration(runId);

      if (!abortController) {
        debugLog(
          '[proceedWithItineraryGeneration] ⏭️ Skipped - startGeneration returned null'
        );
        return;
      }

      // Set expand-in-progress flag to prevent cascade with preference auto-regen
      useDocumentStore.getState().setExpandInProgress(true);

      // Set local UI generation state immediately
      setUiGeneration({ active: true, stage: 'itinerary' });

      // Timeout handling
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      const resetTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          if (storeIsCurrentRun(runId)) {
            setUiGeneration({
              active: true,
              stage: 'itinerary',
              message: 'Still working...',
            });
          }
        }, STREAM_TIMEOUT_MS);
      };

      resetTimeout();

      try {
        // FIX: Read LIVE state from store to avoid stale closure
        // The callback can be triggered immediately after a Zustand merge, but before
        // React re-renders. Using getState() ensures we get the merged strategy_sections.
        const freshState = useDocumentStore.getState();
        const currentDoc = freshState.document;
        const preferredTileIds = freshState.preferredTileIds;

        // Build preferences from heart state
        const tiles = currentDoc?.tiles ?? {};
        const preferredHotelIds: string[] = [];
        const preferredActivityIds: string[] = [];

        // Categorize preferred tiles by type (handle various type variants)
        for (const tileId of preferredTileIds) {
          const tile = tiles[tileId];
          const tileType = (tile?.type || '').toLowerCase();
          if (tile) {
            // Match hotel variants
            if (
              tileType === 'hotel' ||
              tileType === 'stay' ||
              tileType === 'accommodation'
            ) {
              preferredHotelIds.push(tileId);
            }
            // Match activity variants
            else if (
              tileType === 'activity' ||
              tileType === 'experience' ||
              tileType === 'tour' ||
              tileType === 'attraction' ||
              tileType === 'excursion' ||
              tileType === 'ticket' ||
              tileType === 'event'
            ) {
              preferredActivityIds.push(tileId);
            }
          }
        }

        // SAFETY: Check if signal was aborted before making the fetch
        if (abortController.signal.aborted) return;

        // SAFETY: Verify we're still the current run right before fetch
        if (!storeIsCurrentRun(runId)) return;

        // Debug: Log what we're sending (using fresh state)
        debugLog('[proceedWithItineraryGeneration] 📦 Sending (fresh state):', {
          strategy_sections: currentDoc?.strategy_sections?.map((s) => ({
            type: s.specialist_type,
            content_added_count: s.content_added?.length ?? 0,
          })),
          force_full_rebuild: options?.forceFullRebuild ?? false,
        });

        const response = await apiFetch('/api/expand-itinerary', {
          method: 'POST',
          body: JSON.stringify({
            idempotency_key: runId,
            // Pass document context so backend can generate itinerary
            trip_inputs: currentDoc?.trip_inputs,
            strategy_sections: currentDoc?.strategy_sections,
            tiles: currentDoc?.tiles,
            // Pass user heart preferences for AI weighting
            preferences:
              preferredHotelIds.length > 0 || preferredActivityIds.length > 0
                ? {
                    preferred_hotel_ids: preferredHotelIds,
                    preferred_activity_ids: preferredActivityIds,
                  }
                : null,
            // Force full rebuild when structural change detected (new specialist added)
            force_full_rebuild: options?.forceFullRebuild ?? false,
          }),
          signal: abortController.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        if (!response.body) {
          setUiGeneration(null);
          if (timeoutId) clearTimeout(timeoutId);
          return;
        }

        await consumeNdjsonEnvelopeStream(response.body, {
          onEnvelope: (planEnvelope) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', 'envelope', { type: 'envelope', plan_envelope: planEnvelope });
            debugLog('[expand-itinerary] Merging envelope:', {
              day_cards: planEnvelope?.day_cards?.length ?? 0,
              plan_view_state: planEnvelope?.plan_view_state,
            });
            storeMergeEnvelope(planEnvelope);
          },
          onProgress: (event) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', event.type, event);
            setUiGeneration({
              active: true,
              stage: event.stage,
              message: event.message,
              pct: event.pct,
            });
          },
          onDone: (event) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', event.type, event);
            debugLog('[expand-itinerary] Generation complete');
            setUiGeneration(null);
            // Sync version from backend to prevent 409 on next PATCH
            // expand-itinerary persists changes which increments version
            if (typeof event.version === 'number') {
              useDocumentStore.setState({ version: event.version });
            }
            // Sync preferences to track which were used in this generation
            storeMarkPreferencesAsApplied();
            // Log warning if some preferred activities couldn't fit
            if (event.dropped_preferred_count && event.dropped_preferred_count > 0) {
              debugLog(
                `[itinerary] ${event.dropped_preferred_count} preferred activities couldn't fit — not enough free days`
              );
            }
            // Show toast for activity reductions (e.g., diving truncated due to no-fly buffer)
            if (event.warnings && event.warnings.length > 0) {
              event.warnings.forEach((warning: string) => {
                addToast(warning, 'info');
              });
            }
          },
          onError: (event) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', event.type, event);
            // CONSTRAINT_CONFLICT is a business-logic response, not an actual error.
            // It contains partial day_cards (what CAN fit) + conflict resolutions.
            let parsed: Record<string, unknown> | null = null;
            try {
              parsed =
                typeof event.message === 'string'
                  ? JSON.parse(event.message)
                  : event.message;
            } catch {
              /* not JSON — treat as generic error */
            }

            if (parsed && parsed.error === 'CONSTRAINT_CONFLICT') {
              debugLog('[expand-itinerary] Constraint conflict:', parsed);
              const dayCards = parsed.day_cards as
                | Array<Record<string, unknown>>
                | undefined;
              if (dayCards && dayCards.length > 0) {
                debugLog(
                  `[expand-itinerary] Storing ${dayCards.length} partial day cards from conflict`
                );
                storeMergeEnvelope({
                  day_cards: dayCards as unknown as PlanDocumentData['day_cards'],
                  plan_view_state:
                    'S3_PARTIAL_CONFLICT' as PlanDocumentData['plan_view_state'],
                });
              }
            } else {
              console.error('[expand-itinerary] Error received:', event.message);
            }
          },
        });
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          debugLog('Itinerary generation aborted');
          return;
        }
        console.error('Failed to expand to itinerary:', error);
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
        // Clear expand-in-progress flag
        useDocumentStore.getState().setExpandInProgress(false);
        if (storeIsCurrentRun(runId)) {
          // Clear generation state to allow re-entry (e.g., structural change auto-expand)
          storeCompleteGeneration();
          setUiGeneration(null);
        }
      }
      // PERF: No storeDocument in deps - function uses getState() for live reads
    },
    [storeStartGeneration, storeIsCurrentRun, storeMergeEnvelope, storeMarkPreferencesAsApplied, storeCompleteGeneration, addToast]
  );

  // ─────────────────────────────────────────────────────────────────────────────
  // PATH A: Auto-Trigger Itinerary for Multi-Specialist Trips
  // ─────────────────────────────────────────────────────────────────────────────
  // When S2_STRATEGY_READY + multi-specialist + hasDates, auto-generate itinerary
  // This removes the need for "Build Itinerary" button in multi-specialist flows
  // @see docs/ux_unified_architecture.md - Path A: Auto-trigger Flow

  // Track if we've already auto-triggered to prevent infinite loops
  const hasAutoTriggeredRef = useRef(false);

  // Track isRegenerating via ref to prevent callback cascade
  // (reading from ref avoids adding isRegenerating to useCallback deps)
  const isRegeneratingRef = useRef(false);

  // Check if itinerary content exists
  const hasItineraryContent = (docDayCards?.length ?? 0) > 0;

  // Reset auto-trigger flag when itinerary is cleared and we're back at S2
  // This handles the S3 → S2 revert when a new specialist is added
  useEffect(() => {
    if (!hasItineraryContent && isStrategyReady(planViewState)) {
      hasAutoTriggeredRef.current = false;
    }
  }, [hasItineraryContent, planViewState]);

  // Sync isRegenerating state to ref (prevents callback cascade when isRegenerating changes)
  useEffect(() => {
    isRegeneratingRef.current = isRegenerating;
  }, [isRegenerating]);

  // Auto-trigger effect
  useEffect(() => {
    // Skip if already triggered
    if (hasAutoTriggeredRef.current) return;

    // RACE GUARD: Skip if regeneration is in progress (e.g., preference auto-regen)
    if (isRegeneratingRef.current) return;

    // RACE GUARD: Skip if itinerary generation is already active
    // (handles case where onAfterRegenerate already started generation)
    if (uiGeneration?.active) return;

    // Check auto-trigger conditions
    const shouldAutoTrigger = shouldAutoTriggerItinerary(
      planViewState,
      docExecutedTopics,
      hasDates,
      uiGeneration,
      hasItineraryContent
    );

    if (shouldAutoTrigger) {
      hasAutoTriggeredRef.current = true;
      // Use setTimeout to avoid triggering during render
      const timer = setTimeout(() => {
        // RE-CHECK: If itinerary was generated by another path (e.g., ChatPanel CATCH_ALL), skip
        const freshDayCards = useDocumentStore.getState().document?.day_cards;
        if (freshDayCards && freshDayCards.length > 0) {
          debugLog(
            '[auto-trigger] ⏭️ Skipped - itinerary already exists from another trigger'
          );
          return;
        }
        proceedWithItineraryGeneration();
      }, 500); // Small delay for UX (let tiles settle)
      return () => clearTimeout(timer);
    }
  }, [
    planViewState,
    docExecutedTopics,
    hasDates,
    uiGeneration,
    hasItineraryContent,
    proceedWithItineraryGeneration,
  ]);

  // Handler for expanding to itinerary - validation gates before generation
  // "Assume & Refine" philosophy: Backend auto-selects recommended stay if none saved
  const handleExpandToItinerary = useCallback(async () => {
    // GATE 0: Don't expand if plan is currently regenerating (race condition prevention)
    // Read from ref to avoid adding isRegenerating to deps (prevents callback cascade)
    if (isRegeneratingRef.current) {
      addToast('Plan is updating, please wait...', 'info');
      return;
    }

    // FIX: Read DIRECTLY from store to avoid stale closure when called via ref
    // (storeDocument from closure may be stale when onAfterRegenerate calls this)
    const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;

    // GATE 1: Require start_date
    if (!currentTripInputs?.start_date) {
      addToast('Set a start date first', 'info');
      return;
    }

    // GATE 2: Require end_date (multi-day trips are Nomadic's core product)
    if (!currentTripInputs?.end_date) {
      addToast('Add return date to see itinerary', 'info');
      return;
    }

    // All gates passed - proceed with itinerary generation
    await proceedWithItineraryGeneration();
  }, [addToast, proceedWithItineraryGeneration]);

  // Handle quick pick from InlineDatePrompt
  const handleSelectNights = useCallback(
    async (nights: number) => {
      const startDate = tripInputs.start_date;
      if (!startDate) return;

      // Calculate end date (timezone-safe)
      const endDateStr = addDaysUTC(startDate, nights);

      // Update trip inputs and await confirmation
      const success = await storeCommitTripInputs({ end_date: endDateStr });

      // Just confirm the date was set - DON'T auto-trigger expand-itinerary
      // User clicks "Build Itinerary" button to continue
      // This prevents race conditions where expand-itinerary runs before plan regenerates
      if (success) {
        addToast('Trip length set', 'confirmation');
      }
    },
    [tripInputs.start_date, addDaysUTC, storeCommitTripInputs, addToast]
  );

  // Handler for "Build plan" CTA in right panel (S0BootstrapView)
  // Triggers plan generation via ChatPanel
  const handleBuildPlan = useCallback(() => {
    chatPanelRef.current?.sendMessage?.(GENERATE_PLAN_TRIGGER);
  }, []);

  // Handler for "Finalize & Unlock Booking" CTA (The Bridge)
  // Sets plan as finalized and navigates to Book view
  const finalizeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (finalizeTimerRef.current) clearTimeout(finalizeTimerRef.current);
  }, []);

  const handleFinalizePlan = useCallback(() => {
    setIsFinalizing(true);

    // Simulate "Scanning best rates..." delay for UX polish
    finalizeTimerRef.current = setTimeout(() => {
      finalizeTimerRef.current = null;
      // Mark plan as finalized (unlocks Book view)
      finalizePlan();
      // Navigate to Book view
      navigateTo('book');
      setIsFinalizing(false);
    }, 1500);
  }, [finalizePlan, navigateTo]);

  // Handler for mobile chat input — guards against ref not ready during first render
  const handleMobileSend = useCallback((message: string) => {
    if (!chatPanelRef.current?.sendMessage) {
      debugLog('[MobileChatInput] ChatPanel ref not ready');
      return;
    }
    chatPanelRef.current.sendMessage(message);
  }, []);

  // Handler for mobile stop streaming
  const handleMobileStopStreaming = useCallback(() => {
    chatPanelRef.current?.stopStreaming?.();
  }, []);

  // Planner content (left panel): ChatPanel (primary funnel with refinements inside)
  const plannerContent = (
    <ErrorBoundary label="Chat">
      <ChatPanel
        ref={chatPanelRef}
        key={chatKey}
        selectedBranchId={selectedBranchId}
        onPlanResult={handlePlanResultWithReceipt}
        onGeneratePlanStart={handleGeneratePlanStartWithSnapshot}
        onAutoExpandItinerary={proceedWithItineraryGeneration}
        fullHeight={false}
        hasBranches={hasBranchesReady}
        readyToGenerate={readyToGenerate}
        isGenerating={isGenerating}
        planState={planState}
        onUserMessageSubmit={handleUserMessageSubmit}
        // Onboarding chips props - click handlers are internal to ChatPanel
        destination={tripInputs.destination ?? undefined}
        origin={tripInputs.origin ?? undefined}
        dateRange={
          hasStartDate && hasEndDate
            ? `${formatDateForDisplay(tripInputs.start_date)} - ${formatDateForDisplay(tripInputs.end_date)}`
            : hasStartDate
              ? `${formatDateForDisplay(tripInputs.start_date)} → ?` // Incomplete state
              : undefined
        }
        budget={
          tripInputs.budget != null ? `$${tripInputs.budget.toLocaleString()}` : undefined
        }
        // CTA gating flags
        hasDestination={hasDestination}
        // Optional Refinements props (now rendered inside ChatPanel)
        hasDates={hasDates}
        tripInputs={tripInputs}
        bookingTypes={bookingTypes}
        flightSettings={flightSettings}
        hotelSettings={hotelSettings}
        activitySettings={activitySettings}
        onUpdateBookingTypes={handleUpdateBookingTypes}
        onUpdateFlightSettings={handleUpdateFlightSettings}
        onUpdateHotelSettings={handleUpdateHotelSettings}
        onUpdateActivitySettings={handleUpdateActivitySettings}
        planViewState={planViewState}
        onOpenSheet={openSheet}
      />
    </ErrorBoundary>
  );

  // Derive sub-stage info for header status display
  const isExpandingItinerary = generation?.stage === 'itinerary';

  // Plan View content (right panel): Stage-aware StrategyStageRenderer
  const planViewContent = (
    <ErrorBoundary label="Plan View">
      <StrategyStageRenderer
        state={planViewState}
        viewModel={planViewModel}
        destinationCard={destinationCard ?? undefined}
        tiles={tiles}
        generation={generation}
        canGeneratePlan={canGeneratePlan}
        fallbackTitle={fallbackTitle}
        hasDates={hasDates}
        isExpandingItinerary={isExpandingItinerary}
        onBuildPlan={handleBuildPlan}
        onExpandToItinerary={handleExpandToItinerary}
        onFinalizePlan={handleFinalizePlan}
        isFinalizing={isFinalizing}
        savedTileIds={preferredTileIds}
        onSaveTile={handleSaveTilePreference}
        tripInputs={tripInputs}
        isCommitting={isCommitting}
        onOpenSheet={openSheet}
        hasEverHadPlan={hasEverHadPlan}
        isRegenerating={isRegenerating}
        onSelectNights={handleSelectNights}
        onOpenActivitySettings={handleOpenGearActivities}
        onOpenStaysSettings={handleOpenGearStays}
        onOpenFlightsSettings={handleOpenGearFlights}
      />
    </ErrorBoundary>
  );

  return (
    <>
      {/* Main app content */}
      <div className="appTopo text-foreground">
        {/* Unified Split Layout - always visible from the start */}
        <SplitLayoutView
          plannerContent={plannerContent}
          planViewContent={planViewContent}
          planState={planState}
          onReset={handleStartNewSession}
          isResetting={isResettingSession}
          planTabEnabled={planTabEnabled}
          mobileStatusBar={
            !isDesktop &&
            (hasDestination ||
              Boolean(tripInputs.origin) ||
              Boolean(tripInputs.start_date)) ? (
              <TripStatusBar
                tripInputs={tripInputs}
                specialists={docExecutedTopics ?? []}
                onOpenSheet={openSheet}
              />
            ) : undefined
          }
          mobileInput={
            !isDesktop ? (
              <MobileChatInput
                onSend={handleMobileSend}
                onStop={handleMobileStopStreaming}
                isProcessing={isGenerating}
                hasDestination={hasDestination}
                hasPlan={hasPlan}
              />
            ) : undefined
          }
          headerContent={
            <div className="flex w-full items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <Compass className="text-primary h-5 w-5" />
                  <span className="text-foreground text-lg font-semibold">Nomadic</span>
                </div>
                <span className="text-foreground hidden text-sm sm:inline">
                  <span className="text-muted-foreground/30 mx-2">|</span>
                  Change your mind. Keep the plan.
                </span>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleStartNewSession}
                disabled={isResettingSession}
                className={`${DS.textSize.micro} font-bold uppercase tracking-widest text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-500 dark:hover:bg-white/5 dark:hover:text-white disabled:opacity-60 disabled:pointer-events-none`}
              >
                {isResettingSession ? (
                  <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="mr-1.5 h-3 w-3" />
                )}
                {isResettingSession ? 'Resetting' : 'Reset'}
              </Button>
            </div>
          }
        />

        {/* Floating Build Button - HIDDEN: Using morphing input button instead */}
        {/* The send button in ChatPanel now morphs into Build when ready */}
        <FloatingBuildButton
          visible={false}
          onClick={handleBuildPlan}
          isGenerating={isGenerating}
          hasEverHadPlan={hasEverHadPlan}
        />

        {/* Floating RefreshButton REMOVED - now inline in PlanHeader */}
        {/* RefreshOverlay REMOVED - inline button provides feedback */}
      </div>

      {/* Trip input sheets - shared between header pills and chat panel */}
      {/* In S1+, header pills are the ONLY interactive surface for trip inputs */}
      {/* Destination sheet LOCKED once set - can only change via full trip reset */}
      <DestinationSheet
        open={activeSheet === 'destination' && !tripInputs.destination}
        onOpenChange={(open) => !open && closeSheet()}
        value={tripInputs.destination || ''}
        onSave={async (value) => {
          // SYNC: Update store immediately so RefreshButton sees new value
          storeUpdateTripInputs({ destination: value });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({ destination: value });
            closeSheet();
            addToast(`Destination: ${value}`, 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <OriginSheet
        open={activeSheet === 'origin'}
        onOpenChange={(open) => !open && closeSheet()}
        value={tripInputs.origin || ''}
        onSave={async (value) => {
          // SYNC: Update store immediately so RefreshButton sees new value
          storeUpdateTripInputs({ origin: value });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({ origin: value });
            closeSheet();
            addToast(`Origin: ${value}`, 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <DatesSheet
        open={activeSheet === 'dates'}
        onOpenChange={(open) => !open && closeSheet()}
        startDate={parseISODateLocal(tripInputs.start_date)}
        endDate={parseISODateLocal(tripInputs.end_date)}
        onSave={async (start, end) => {
          // Use local date components to avoid timezone shifts
          // toISOString() converts to UTC which can shift the date by a day
          const startStr = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
          const endStr = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`;
          // SYNC: Update store immediately so RefreshButton sees new value
          storeUpdateTripInputs({
            start_date: startStr,
            end_date: endStr,
          });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({
              start_date: startStr,
              end_date: endStr,
            });
            closeSheet();

            // Trigger itinerary rebuild if one exists
            const hasItinerary =
              (useDocumentStore.getState().document?.day_cards?.length ?? 0) > 0;
            if (hasItinerary) {
              proceedWithItineraryGeneration({ forceFullRebuild: true });
            }
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <TravelersSheet
        open={activeSheet === 'travelers'}
        onOpenChange={(open) => !open && closeSheet()}
        adults={tripInputs.adults ?? 1}
        children={tripInputs.children ?? 0}
        onSave={async (adults, children) => {
          // SYNC: Update store immediately
          storeUpdateTripInputs({ adults, children });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({ adults, children });
            closeSheet();
            const label = `${adults} adult${adults > 1 ? 's' : ''}${children > 0 ? `, ${children} child${children > 1 ? 'ren' : ''}` : ''}`;
            addToast(`Travelers: ${label}`, 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <BudgetSheet
        open={activeSheet === 'budget'}
        onOpenChange={(open) => !open && closeSheet()}
        amount={tripInputs.budget ?? null}
        currency={tripInputs.currency || 'USD'}
        budgetType="total"
        onSave={async (amount, currency) => {
          // SYNC: Update store immediately
          storeUpdateTripInputs({ budget: amount, currency });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({ budget: amount, currency });
            closeSheet();
            const formatted = new Intl.NumberFormat('en-US', {
              style: 'currency',
              currency,
              maximumFractionDigits: 0,
            }).format(amount);
            addToast(`Budget: ${formatted}`, 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      {/* Activity settings sheet - opened from gear icons + Activities pill */}
      <ActivitiesSheet
        open={gearActivitiesSheetOpen || activeSheet === 'activities'}
        onOpenChange={(open) => {
          setGearActivitiesSheetOpen(open);
          if (!open) closeSheet();
        }}
        enabled={true}
        settings={tripInputs.activity_settings || { categories: [], skill_level: null }}
        hasDestination={hasDestination}
        onToggle={() => {}} // No-op - toggle handled by module toggle in ChatPanel
        onSaveSettings={(settings) => {
          handleUpdateActivitySettings(settings);
          setGearActivitiesSheetOpen(false);
          closeSheet();
          addToast('Activity preferences saved', 'confirmation');
          // Trigger plan regeneration if plan is active
          const isActive = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
            planViewState
          );
          if (isActive) {
            chatPanelRef.current?.sendMessage?.(GENERATE_PLAN_TRIGGER);
          }
        }}
      />

      {/* Stays settings sheet - opened from gear icons on hotel/check-in blocks */}
      <StaysSheet
        open={gearStaysSheetOpen}
        onOpenChange={setGearStaysSheetOpen}
        enabled={true}
        settings={tripInputs.hotel_settings || { min_stars: 0, amenities: [] }}
        hasDestination={hasDestination}
        hasDates={hasDates}
        onToggle={() => {}} // No-op - toggle handled by module toggle in ChatPanel
        onSaveSettings={async (settings) => {
          try {
            await storeCommitTripInputs({ hotel_settings: settings });
            setGearStaysSheetOpen(false);
            addToast('Hotel preferences saved', 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
        onOpenDestination={() => openSheet('destination')}
        onOpenDates={() => openSheet('dates')}
      />

      {/* Flights settings sheet - opened from gear icons on arrival/departure blocks */}
      <FlightsSheet
        open={gearFlightsSheetOpen}
        onOpenChange={setGearFlightsSheetOpen}
        enabled={true}
        settings={
          tripInputs.flight_settings || {
            round_trip: true,
            cabin_class: 'economy',
            direct_only: false,
          }
        }
        hasOrigin={hasOrigin}
        hasDestination={hasDestination}
        hasDates={hasDates}
        onToggle={() => {}} // No-op - toggle handled by module toggle in ChatPanel
        onSaveSettings={async (settings) => {
          try {
            await storeCommitTripInputs({ flight_settings: settings });
            setGearFlightsSheetOpen(false);
            addToast('Flight preferences saved', 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
        onOpenOrigin={() => openSheet('origin')}
        onOpenDestination={() => openSheet('destination')}
        onOpenDates={() => openSheet('dates')}
      />

      {/* Trip settings relay sheet - opened from TripStatusBar pencil icon */}
      <TripSettingsSheet
        open={activeSheet === 'trip-settings'}
        onOpenChange={(open) => !open && closeSheet()}
        tripInputs={tripInputs}
        onOpenSheet={openSheet}
      />
    </>
  );
}

// Inner component with startup animation
function AppWithStartup() {
  const [hasBooted, setHasBooted] = useState(false);

  return (
    <>
      {!hasBooted && <StartupSequence onComplete={() => setHasBooted(true)} />}
      <div
        className={
          hasBooted ? 'opacity-100 transition-opacity duration-300' : 'opacity-0'
        }
      >
        <ErrorBoundary label="App">
          <NomadicLanding />
        </ErrorBoundary>
      </div>
    </>
  );
}

export default function NomadicLandingWithProvider() {
  return <AppWithStartup />;
}
