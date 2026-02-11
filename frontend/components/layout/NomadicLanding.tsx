'use client';

// date-fns imports removed - no longer needed after TripDetailsForm removal
import { Compass, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

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
import { shouldAutoTriggerItinerary } from '@/components/plan/planStateHelpers';
import {
  ActivitiesSheet,
  BudgetSheet,
  DatesSheet,
  DestinationSheet,
  FlightsSheet,
  OriginSheet,
  StaysSheet,
  TravelersSheet,
} from '@/components/plan/sheets';
import { TripSettingsSheet } from '@/components/plan/sheets/TripSettingsSheet';
import { StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { usePreferenceAutoRegen } from '@/hooks/usePreferenceAutoRegen';
import { useSheetManager } from '@/hooks/useSheetManager';
import { useShortlist } from '@/hooks/useShortlist';
import { useSpecialistDeepLink } from '@/hooks/useSpecialistDeepLink';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { apiFetch, fetchDestinationImage } from '@/lib/api';
import { parseISODateLocal } from '@/lib/date-utils';
import type { SpecialistType } from '@/lib/specialistLinkParser';
import { createStreamParser, type StreamEvent } from '@/lib/streamParser';
import { formatDateForDisplay } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import type { DocumentTripInputs, PlanDocumentData } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanState, PlanViewModel, PlanViewState } from '@/types/plan-envelope';

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
  const mobileNavigateToPlan = useMobileNavStore((s) => s.navigateToPlan);
  const mobileNavReset = useMobileNavStore((s) => s.reset);
  const mobileSetHasNewContent = useMobileNavStore((s) => s.setHasNewPlanContent);

  // Document store - single source of truth for trip inputs
  const documentStore = useDocumentStore();
  // Use direct selector for trip_inputs to ensure reactivity on updates
  const storeTripInputs = useDocumentStore((state) => state.document?.trip_inputs);
  // Stable selector for setActiveView (avoids infinite loops in useEffect)
  const setActiveView = useDocumentStore((state) => state.setActiveView);
  const llmUpdatedFields = documentStore.llmUpdatedFields;
  const acknowledgeLLMUpdate = documentStore.acknowledgeLLMUpdate;
  const restoreTripInputs = documentStore.restoreTripInputs;
  const isCommitting = documentStore.isCommitting;

  // Sheet manager - shared between header pills and chat panel
  // In S1+, header pills are the only interactive surface for trip inputs
  const { activeSheet, openSheet, closeSheet } = useSheetManager();

  // View navigation - decoupled from plan_view_state
  const {
    navigateTo,
    hasLeftSetup: _hasLeftSetup,
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
  const [lastGenerationError, setLastGenerationError] = useState<string | null>(null);

  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);

  // Use hook for local booking settings state management
  const {
    bookingTypes,
    flightSettings,
    hotelSettings,
    transportSettings,
    activitySettings,
    handleUpdateBookingTypes,
    handleUpdateFlightSettings,
    handleUpdateHotelSettings,
    handleUpdateTransportSettings,
    handleUpdateActivitySettings,
    handleAddActivity,
    handleRemoveActivity,
  } = useLocalBookingSettings(storeTripInputs, addToast);

  // Shortlist hook - manages user's saved tiles in S2
  const shortlist = useShortlist();

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

    // Note: fetchDestinationImage uses apiFetch which doesn't accept signal yet,
    // so we check abort status after the fetch completes
    fetchDestinationImage(destination)
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
          console.warn('Failed to fetch destination image:', err);
        }
      });

    return () => controller.abort();
  }, [tripInputs.destination]);

  // Branch manager hook - manages branches, tiles, and generating state
  const branchManager = useBranchManager({
    tripInputs,
    chatPanelContainerRef,
    chatPanelRef,
    hasEverHadPlan,
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
    console.log('[handleStartNewSession] 🔄 Reset triggered');
    try {
      // CRITICAL: Reset document store FIRST (synchronously) to prevent stale state
      // from causing incorrect planViewState computation during async operations
      documentStore.reset();
      // Reset chat store synchronously so empty state ("Where to next?") shows
      // immediately — don't wait for async branchManagerStartNewSession network calls
      useChatStore.getState().resetChat();
      console.log(
        '[handleStartNewSession] ✅ documentStore.reset() + chatStore.resetChat() done'
      );
      // Clear shortlist (saved tiles)
      shortlist.clear();
      // Clear local UI generation state
      setUiGeneration(null);
      setLastGenerationError(null);
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
      console.log('[handleStartNewSession] ⏳ Calling branchManagerStartNewSession...');
      await branchManagerStartNewSession();
      console.log('[handleStartNewSession] ✅ Reset complete');
    } catch (error) {
      console.error('[handleStartNewSession] ❌ Reset failed:', error);
    }
  }, [
    shortlist,
    branchManagerStartNewSession,
    closeSheet,
    documentStore,
    isDesktop,
    mobileNavReset,
  ]);

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
      // Use documentStore.document directly to avoid variable scope issues
      const existingTopics = new Set(
        documentStore.document?.executed_strategy_topics ?? []
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
    [hasEverHadPlan, documentStore.document?.executed_strategy_topics]
  );

  // Receipt undo/dismiss handlers removed - re-add when receipt UI is implemented
  // Uses: previousTripInputsRef, storeTripInputs, restoreTripInputs, setReceiptData, detectChangedFieldNames
  void restoreTripInputs; // Silence unused variable warning

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

  // Destructure commonly used values from the hook
  // Note: resetDraft is accessed via tripInputsEditorRef.current in branchManager callback
  const { handleUpdateAdults, handleUpdateChildren, handleToggleRequiresAssistance } =
    tripInputsEditor;

  const missingFields = tripInputs.missing_fields ?? [];

  // Check if we have origin or destination to show route
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination = Boolean(tripInputs.destination);
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);

  // NEW: Derive plan state envelope fields
  // Use backend-provided plan_state if available, otherwise derive from local state
  // GRANULAR SELECTORS: Each field subscribes independently to reduce re-render cascade
  // @see docs/ux_unified_architecture.md - Performance: Zustand selector granularity
  const docPlanState = useDocumentStore((s) => s.document?.plan_state);
  const docDestinationCard = useDocumentStore((s) => s.document?.destination_card);
  const docPlanViewState = useDocumentStore((s) => s.document?.plan_view_state);
  const docStrategySections = useDocumentStore((s) => s.document?.strategy_sections);
  const docTiles = useDocumentStore((s) => s.document?.tiles);
  const docExecutedTopics = useDocumentStore((s) => s.document?.executed_strategy_topics);
  const docPendingTopics = useDocumentStore((s) => s.document?.pending_strategy_topics);
  const docDayCards = useDocumentStore((s) => s.document?.day_cards);
  const docGeneration = useDocumentStore((s) => s.document?.generation);
  const docOpenDecisions = useDocumentStore((s) => s.document?.open_decisions);
  const docItineraryOverview = useDocumentStore((s) => s.document?.itinerary_overview);
  const docItineraryAssumptions = useDocumentStore(
    (s) => s.document?.itinerary_assumptions
  );
  const docNeedsRefresh = useDocumentStore((s) => s.document?.needs_refresh);
  const docCanExpand = useDocumentStore((s) => s.document?.can_expand_to_itinerary);

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
  const destinationCard =
    docDestinationCard ??
    (hasDestination
      ? {
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
          // Use fetched destination image URL (from Unsplash API)
          image_url: destinationImageUrl ?? undefined,
        }
      : undefined);

  // Booking status (from backend, for per-tab display) - kept for future booking UI

  // Plan View State (for StrategyStageRenderer)
  // Use backend's plan_view_state if available, otherwise derive locally
  const backendPlanViewState = docPlanViewState;
  const hasStrategyContent = (docStrategySections?.length ?? 0) > 0;

  // Update hasEverHadPlan when plan content becomes available
  // Tiles indicate plan is ready
  // Using state ensures useMemo re-computes when this changes
  const hasTilesReady = Object.keys(docTiles ?? {}).length > 0;
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
  const executedTopics = docExecutedTopics ?? [];
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
    if (planViewState === 'S1_FRAMING') {
      if (!isDesktop) {
        mobileNavigateToPlan(); // Auto-swipe to plan page
      }
      // Desktop: Update activeView in store
      setActiveView('planning');
    }
  }, [isDesktop, planViewState, mobileNavigateToPlan, setActiveView]);

  // Mobile badge: plan content updated while user is on chat page
  const mobileActivePage = useMobileNavStore((s) => s.activePage);
  const tileCount = Object.keys(docTiles ?? {}).length;
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
  const tiles = docTiles ?? {};

  // Plan tab enabled when we have branches/plan content (unlocked after Build)
  const planTabEnabled = useMemo(() => {
    // Plan is available if we have branches or are past S0
    return hasBranchesReady || planViewState !== 'S0_BOOTSTRAP';
  }, [hasBranchesReady, planViewState]);

  // Book tab enabled when we have tiles or in a state that can show booking content
  const bookTabEnabled = useMemo(() => {
    const hasTiles = Object.keys(tiles).length > 0;
    const inBookableState = [
      'S2_STRATEGY_READY',
      'S3_ITINERARY_READY',
      'S3_EDITING',
    ].includes(planViewState);
    return hasTiles || inBookableState;
  }, [tiles, planViewState]);

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
        console.log(
          '[proceedWithItineraryGeneration] ⏭️ Skipped - generation already registered:',
          existingRunId
        );
        return;
      }

      // RACE GUARD: Check if expand is already in progress (prevents cascade)
      if (useDocumentStore.getState().expandInProgress) {
        console.log(
          '[proceedWithItineraryGeneration] ⏭️ Skipped - expandInProgress flag set'
        );
        return;
      }

      // Generate runId for this generation (also serves as idempotency key)
      const runId = crypto.randomUUID();

      // Start generation in documentStore - gets AbortController and registers runId
      // ATOMIC: startGeneration returns null if another generation is already running
      const abortController = documentStore.startGeneration(runId);

      if (!abortController) {
        console.log(
          '[proceedWithItineraryGeneration] ⏭️ Skipped - startGeneration returned null'
        );
        return;
      }

      // Set expand-in-progress flag to prevent cascade with preference auto-regen
      useDocumentStore.getState().setExpandInProgress(true);

      // Set local UI generation state immediately
      setUiGeneration({ active: true, stage: 'itinerary' });
      setLastGenerationError(null);

      // Timeout handling
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      const resetTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          if (documentStore.isCurrentRun(runId)) {
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
        if (!documentStore.isCurrentRun(runId)) return;

        // Debug: Log what we're sending (using fresh state)
        console.log('[proceedWithItineraryGeneration] 📦 Sending (fresh state):', {
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
          setLastGenerationError('Streaming not supported. Please retry.');
          setUiGeneration(null);
          if (timeoutId) clearTimeout(timeoutId);
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        const parser = createStreamParser((event: StreamEvent) => {
          if (!documentStore.isCurrentRun(runId)) {
            console.debug('Ignoring late event from stale run');
            return;
          }

          resetTimeout();

          console.debug('[expand-itinerary] Received event:', event.type, event);
          if (event.type === 'envelope') {
            console.debug('[expand-itinerary] Merging envelope:', {
              day_cards: event.plan_envelope?.day_cards?.length ?? 0,
              plan_view_state: event.plan_envelope?.plan_view_state,
            });
            documentStore.mergeEnvelope(event.plan_envelope);
          } else if (event.type === 'progress') {
            setUiGeneration({
              active: true,
              stage: event.stage,
              message: event.message,
              pct: event.pct,
            });
          } else if (event.type === 'done') {
            console.debug('[expand-itinerary] Generation complete');
            setUiGeneration(null);
            setLastGenerationError(null);
            // Sync version from backend to prevent 409 on next PATCH
            // expand-itinerary persists changes which increments version
            if (typeof event.version === 'number') {
              useDocumentStore.setState({ version: event.version });
            }
            // Sync preferences to track which were used in this generation
            documentStore.markPreferencesAsApplied();
            // Log warning if some preferred activities couldn't fit
            if (event.dropped_preferred_count && event.dropped_preferred_count > 0) {
              console.warn(
                `[itinerary] ⚠️ ${event.dropped_preferred_count} preferred activities couldn't fit — not enough free days`
              );
            }
            // Show toast for activity reductions (e.g., diving truncated due to no-fly buffer)
            if (event.warnings && event.warnings.length > 0) {
              event.warnings.forEach((warning: string) => {
                addToast(warning, 'info');
              });
            }
          } else if (event.type === 'error') {
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
              console.warn('[expand-itinerary] Constraint conflict:', parsed);
              const dayCards = parsed.day_cards as
                | Array<Record<string, unknown>>
                | undefined;
              if (dayCards && dayCards.length > 0) {
                console.debug(
                  `[expand-itinerary] Storing ${dayCards.length} partial day cards from conflict`
                );
                documentStore.mergeEnvelope({
                  day_cards: dayCards as unknown as PlanDocumentData['day_cards'],
                  plan_view_state:
                    'S3_PARTIAL_CONFLICT' as PlanDocumentData['plan_view_state'],
                });
              }
            } else {
              console.error('[expand-itinerary] Error received:', event.message);
              setLastGenerationError(event.message || 'Failed to generate itinerary');
            }
          }
        });

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          parser.feed(decoder.decode(value, { stream: true }));
        }
        parser.flush();
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          console.debug('Itinerary generation aborted');
          return;
        }
        console.error('Failed to expand to itinerary:', error);
        setLastGenerationError('Something went wrong. Please try again.');
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
        // Clear expand-in-progress flag
        useDocumentStore.getState().setExpandInProgress(false);
        if (documentStore.isCurrentRun(runId)) {
          // Clear generation state to allow re-entry (e.g., structural change auto-expand)
          documentStore.completeGeneration();
          setUiGeneration(null);
        }
      }
      // PERF: No storeDocument in deps - function uses getState() for live reads
    },
    [shortlist.savedTileIds, documentStore]
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
    if (!hasItineraryContent && planViewState === 'S2_STRATEGY_READY') {
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
      setTimeout(() => {
        // RE-CHECK: If itinerary was generated by another path (e.g., ChatPanel CATCH_ALL), skip
        const freshDayCards = useDocumentStore.getState().document?.day_cards;
        if (freshDayCards && freshDayCards.length > 0) {
          console.log(
            '[auto-trigger] ⏭️ Skipped - itinerary already exists from another trigger'
          );
          return;
        }
        proceedWithItineraryGeneration();
      }, 500); // Small delay for UX (let tiles settle)
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
      const success = await documentStore.commitTripInputs({ end_date: endDateStr });

      // Just confirm the date was set - DON'T auto-trigger expand-itinerary
      // User clicks "Build Itinerary" button to continue
      // This prevents race conditions where expand-itinerary runs before plan regenerates
      if (success) {
        addToast('Trip length set', 'confirmation');
      }
    },
    [tripInputs.start_date, addDaysUTC, documentStore, addToast]
  );

  // Handler for "Build plan" CTA in right panel (S0BootstrapView)
  // Triggers plan generation via ChatPanel
  const handleBuildPlan = useCallback(() => {
    chatPanelRef.current?.sendMessage?.(GENERATE_PLAN_TRIGGER);
  }, []);

  // Handler for "Finalize & Unlock Booking" CTA (The Bridge)
  // Sets plan as finalized and navigates to Book view
  const handleFinalizePlan = useCallback(async () => {
    setIsFinalizing(true);

    // Simulate "Scanning best rates..." delay for UX polish
    await new Promise((resolve) => setTimeout(resolve, 1500));

    // Mark plan as finalized (unlocks Book view)
    finalizePlan();

    // Navigate to Book view
    navigateTo('book');

    setIsFinalizing(false);
  }, [finalizePlan, navigateTo]);

  // Handler for mobile chat input — guards against ref not ready during first render
  const handleMobileSend = useCallback((message: string) => {
    if (!chatPanelRef.current?.sendMessage) {
      console.warn('[MobileChatInput] ChatPanel ref not ready');
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
    <ChatPanel
      ref={chatPanelRef}
      key={chatKey}
      selectedBranchId={selectedBranchId}
      onPlanResult={handlePlanResultWithReceipt}
      onGeneratePlanStart={handleGeneratePlanStartWithSnapshot}
      onFreshStart={handleStartNewSession}
      onAutoExpandItinerary={proceedWithItineraryGeneration}
      fullHeight={false}
      hasBranches={hasBranchesReady}
      readyToGenerate={readyToGenerate}
      isGenerating={isGenerating}
      planState={planState}
      hasEverHadPlan={hasEverHadPlan}
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
      dateFlex={tripInputs.date_flex}
      tripDuration={tripInputs.trip_duration ?? undefined}
      // CTA gating flags
      hasDestination={hasDestination}
      canGeneratePlan={canGeneratePlan}
      hasPlan={hasPlan}
      // Optional Refinements props (now rendered inside ChatPanel)
      hasDates={hasDates}
      tripInputs={tripInputs}
      bookingTypes={bookingTypes}
      flightSettings={flightSettings}
      hotelSettings={hotelSettings}
      activitySettings={activitySettings}
      transportSettings={transportSettings}
      onUpdateBookingTypes={handleUpdateBookingTypes}
      onUpdateFlightSettings={handleUpdateFlightSettings}
      onUpdateHotelSettings={handleUpdateHotelSettings}
      onUpdateActivitySettings={handleUpdateActivitySettings}
      onUpdateTransportSettings={handleUpdateTransportSettings}
      onAddActivity={handleAddActivity}
      onRemoveActivity={handleRemoveActivity}
      onUpdateAdults={handleUpdateAdults}
      onUpdateChildren={handleUpdateChildren}
      onToggleRequiresAssistance={handleToggleRequiresAssistance}
      llmUpdatedFields={llmUpdatedFields}
      onAcknowledgeLLMUpdate={acknowledgeLLMUpdate}
      planViewState={planViewState}
      onOpenSheet={openSheet}
      // Note: onOpenBudgetInput not wired - falls back to chat insertion.
      // Users can also click budget pill in OptionalRefinementsSection directly.
    />
  );

  // Derive sub-stage info for header status display
  const isExpandingItinerary = generation?.stage === 'itinerary';
  const currentSubStage = generation?.stage ?? null;

  // Plan View content (right panel): Stage-aware StrategyStageRenderer
  const planViewContent = (
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
      currentSubStage={currentSubStage}
      onBuildPlan={handleBuildPlan}
      onExpandToItinerary={handleExpandToItinerary}
      onFinalizePlan={handleFinalizePlan}
      isFinalizing={isFinalizing}
      onReset={handleStartNewSession}
      lastError={lastGenerationError}
      onRetry={handleExpandToItinerary}
      savedTileIds={shortlist.savedTileIds}
      onSaveTile={shortlist.toggleItem}
      tripInputs={tripInputs}
      isCommitting={isCommitting}
      onOpenSheet={openSheet}
      hasEverHadPlan={hasEverHadPlan}
      isRegenerating={isRegenerating}
      onSelectNights={handleSelectNights}
      onOpenActivitySettings={() => setGearActivitiesSheetOpen(true)}
      onOpenStaysSettings={() => setGearStaysSheetOpen(true)}
      onOpenFlightsSettings={() => setGearFlightsSheetOpen(true)}
    />
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
          hasDestination={hasDestination}
          onReset={handleStartNewSession}
          onSendMessage={handleMobileSend}
          isProcessing={isGenerating}
          planTabEnabled={planTabEnabled}
          bookTabEnabled={bookTabEnabled}
          onSelectDates={() => openSheet('dates')}
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
                className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-500 dark:hover:bg-white/5 dark:hover:text-white"
              >
                <RotateCcw className="mr-1.5 h-3 w-3" />
                Reset
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
          documentStore.updateTripInputs({ destination: value });
          // ASYNC: Persist to backend
          await documentStore.commitTripInputs({ destination: value });
          closeSheet();
          addToast(`Destination: ${value}`, 'confirmation');
        }}
      />

      <OriginSheet
        open={activeSheet === 'origin'}
        onOpenChange={(open) => !open && closeSheet()}
        value={tripInputs.origin || ''}
        onSave={async (value) => {
          // SYNC: Update store immediately so RefreshButton sees new value
          documentStore.updateTripInputs({ origin: value });
          // ASYNC: Persist to backend
          await documentStore.commitTripInputs({ origin: value });
          closeSheet();
          addToast(`Origin: ${value}`, 'confirmation');
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
          documentStore.updateTripInputs({
            start_date: startStr,
            end_date: endStr,
          });
          // ASYNC: Persist to backend
          await documentStore.commitTripInputs({
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
        }}
      />

      <TravelersSheet
        open={activeSheet === 'travelers'}
        onOpenChange={(open) => !open && closeSheet()}
        adults={tripInputs.adults ?? 1}
        children={tripInputs.children ?? 0}
        onSave={async (adults, children) => {
          // SYNC: Update store immediately
          documentStore.updateTripInputs({ adults, children });
          // ASYNC: Persist to backend
          await documentStore.commitTripInputs({ adults, children });
          closeSheet();
          const label = `${adults} adult${adults > 1 ? 's' : ''}${children > 0 ? `, ${children} child${children > 1 ? 'ren' : ''}` : ''}`;
          addToast(`Travelers: ${label}`, 'confirmation');
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
          documentStore.updateTripInputs({ budget: amount, currency });
          // ASYNC: Persist to backend
          await documentStore.commitTripInputs({ budget: amount, currency });
          closeSheet();
          const formatted = new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency,
            maximumFractionDigits: 0,
          }).format(amount);
          addToast(`Budget: ${formatted}`, 'confirmation');
        }}
      />

      {/* Activity settings sheet - opened from gear icons on specialist cards */}
      <ActivitiesSheet
        open={gearActivitiesSheetOpen}
        onOpenChange={setGearActivitiesSheetOpen}
        enabled={true}
        settings={tripInputs.activity_settings || { categories: [], skill_level: null }}
        hasDestination={hasDestination}
        onToggle={() => {}} // No-op - toggle handled by module toggle in ChatPanel
        onSaveSettings={async (settings) => {
          await documentStore.commitTripInputs({ activity_settings: settings });
          setGearActivitiesSheetOpen(false);
          addToast('Activity preferences saved', 'confirmation');
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
          await documentStore.commitTripInputs({ hotel_settings: settings });
          setGearStaysSheetOpen(false);
          addToast('Hotel preferences saved', 'confirmation');
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
          await documentStore.commitTripInputs({ flight_settings: settings });
          setGearFlightsSheetOpen(false);
          addToast('Flight preferences saved', 'confirmation');
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
        <NomadicLanding />
      </div>
    </>
  );
}

export default function NomadicLandingWithProvider() {
  return <AppWithStartup />;
}
