'use client';

// date-fns imports removed - no longer needed after TripDetailsForm removal
import { Compass, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { StartupSequence } from '@/components/animations/StartupSequence';
import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { FloatingBuildButton } from '@/components/layout/FloatingBuildButton';
import {
  type PlanResultPayload,
  useBranchManager,
} from '@/components/layout/hooks/useBranchManager';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import { BookingSection } from '@/components/plan/BookingSection';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import {
  BudgetSheet,
  DatesSheet,
  DestinationSheet,
  OriginSheet,
  TravelersSheet,
} from '@/components/plan/sheets';
import { StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useToast } from '@/components/ui/toast';
import { MobileModeProvider, useMobileMode } from '@/contexts/MobileModeContext';
import { useSheetManager } from '@/hooks/useSheetManager';
import { useShortlist } from '@/hooks/useShortlist';
import { useSpecialistDeepLink } from '@/hooks/useSpecialistDeepLink';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { apiFetch, fetchDestinationImage } from '@/lib/api';
import type { SpecialistType } from '@/lib/specialistLinkParser';
import { createStreamParser, type StreamEvent } from '@/lib/streamParser';
import { formatDateForDisplay } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER } from '@/state/chatStore';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanState, PlanViewModel, PlanViewState } from '@/types/plan-envelope';

/**
 * Parse ISO date string (yyyy-MM-dd) as local midnight.
 * Avoids timezone issues where new Date("2026-01-26") is interpreted as UTC.
 */
function parseISODateLocal(dateStr: string | null | undefined): Date | null {
  if (!dateStr) return null;
  const parts = dateStr.split('-');
  if (parts.length === 3) {
    const year = parseInt(parts[0], 10);
    const month = parseInt(parts[1], 10);
    const day = parseInt(parts[2], 10);
    if (!isNaN(year) && !isNaN(month) && !isNaN(day)) {
      return new Date(year, month - 1, day);
    }
  }
  return null;
}

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
  // Mobile mode context - for switching between planner/plan views on mobile
  const { isDesktop, switchToPlan, switchToPlanner, activeTab, setPlanTabHasUpdate } =
    useMobileMode();

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
  const { navigateTo, hasLeftSetup, finalizePlan, canViewPlan, activeView } = useViewNavigation();

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

  // Derive tripInputs from store (with defaults)
  const tripInputs: DocumentTripInputs = useMemo(() => {
    if (!storeTripInputs) return DEFAULT_TRIP_INPUTS;
    return { ...DEFAULT_TRIP_INPUTS, ...storeTripInputs };
  }, [storeTripInputs]);

  // Toast system - use centralized ToastProvider
  const { toast } = useToast();

  // Wrapper for legacy addToast signature (message, type) -> toast(message, { type })
  // Maps 'confirmation' type to 'success' since ToastProvider only supports standard types
  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    // Map legacy 'confirmation' type to 'success' for the unified toast system
    const mappedType = type === 'confirmation' ? 'success' : type;
    toast(message, { type: mappedType as 'success' | 'info' | 'warning' | 'error' });
  }, [toast]);

  // Local UI generation state (fallback if backend doesn't emit generation in envelope)
  const [uiGeneration, setUiGeneration] = useState<GenerationState | null>(null);
  const [lastGenerationError, setLastGenerationError] = useState<string | null>(null);

  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);

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
    handleAddActivity,
    handleRemoveActivity,
  } = useLocalBookingSettings(storeTripInputs, addToast);

  // Shortlist hook - manages user's saved tiles in S2
  const shortlist = useShortlist();

  // Confirmation dialog for destructive Setup click (from Plan/Book mode)
  const [setupConfirmDialogOpen, setSetupConfirmDialogOpen] = useState(false);

  // Destination image state - fetched from Unsplash when destination changes
  const [destinationImageUrl, setDestinationImageUrl] = useState<string | null>(null);
  const lastFetchedDestination = useRef<string | null>(null);

  // Fetch destination image when destination changes
  useEffect(() => {
    const destination = tripInputs.destination;
    if (!destination || destination === lastFetchedDestination.current) return;

    lastFetchedDestination.current = destination;
    setDestinationImageUrl(null); // Clear while loading

    fetchDestinationImage(destination)
      .then((res) => {
        // Only update if this is still the current destination
        if (lastFetchedDestination.current === destination) {
          setDestinationImageUrl(res.image_url);
        }
      })
      .catch((err) => {
        console.warn('Failed to fetch destination image:', err);
      });
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
    // CRITICAL: Reset document store FIRST (synchronously) to prevent stale state
    // from causing incorrect planViewState computation during async operations
    documentStore.reset();
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
    // Close any open trip input sheet
    closeSheet();
    // Reset mobile mode to planner view (shows chat/setup)
    if (!isDesktop) {
      switchToPlanner();
    }
    // Proceed with branch manager reset (clears server session, chat, branches, etc.)
    await branchManagerStartNewSession();
  }, [
    shortlist,
    branchManagerStartNewSession,
    closeSheet,
    documentStore,
    isDesktop,
    switchToPlanner,
  ]);

  // Wrapped handlers for receipt functionality
  // Snapshot trip inputs before generation starts + switch to Plan Mode on mobile
  const handleGeneratePlanStartWithSnapshot = useCallback(() => {
    previousTripInputsRef.current = storeTripInputs ? { ...storeTripInputs } : null;
    setUserRequestedGeneration(true); // Track explicit user request for Plan tab
    handleGeneratePlanStart();
    // Navigate to Plan view when generation starts
    navigateTo('plan');
    // Switch to Plan Mode on mobile when generation starts
    if (!isDesktop) {
      switchToPlan();
    }
  }, [storeTripInputs, handleGeneratePlanStart, navigateTo, isDesktop, switchToPlan]);

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
  // CRITICAL: Use selector for reactivity - accessing documentStore.document directly won't re-render
  const storeDocument = useDocumentStore((state) => state.document);
  const documentPlanState = storeDocument?.plan_state;
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
    storeDocument?.destination_card ??
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
  const backendPlanViewState = storeDocument?.plan_view_state;
  const hasStrategyContent = (storeDocument?.strategy_sections?.length ?? 0) > 0;

  // Update hasEverHadPlan when plan content becomes available
  // Tiles indicate plan is ready
  // Using state ensures useMemo re-computes when this changes
  const hasTilesReady = Object.keys(storeDocument?.tiles ?? {}).length > 0;
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
  }, [
    hasBranchesReady,
    hasStrategyContent,
    hasEverHadPlan,
    userRequestedGeneration,
    hasTilesReady,
  ]);

  // Clear local pending topics when backend responds with executed_strategy_topics
  // Topics that appear in executed are successfully processed
  // Topics that were pending but didn't execute stay (backend didn't process them)
  const executedTopics = storeDocument?.executed_strategy_topics ?? [];
  useEffect(() => {
    if (executedTopics.length > 0) {
      setLocalPendingTopics((prev) =>
        prev.filter((topic) => !executedTopics.includes(topic))
      );
    }
  }, [executedTopics]);

  // Badge notification: Track when specialists update (for Plan tab badge on mobile)
  // @see docs/ux_unified_architecture.md Section X - Mobile Toast Notifications
  const lastSeenTopicsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const executed = new Set(executedTopics);
    const newTopics = [...executed].filter((t) => !lastSeenTopicsRef.current.has(t));
    const hasNew = newTopics.length > 0;
    // Show badge + toast when new topics executed AND user is not on Plan tab
    if (hasNew && activeTab !== 'plan') {
      setPlanTabHasUpdate(true);
      // Mobile UX: Toast notification for hidden canvas updates
      const topicLabel = newTopics[0].charAt(0).toUpperCase() + newTopics[0].slice(1);
      toast(`Plan Updated: ${topicLabel} Strategy Added`);
    }
    // Update last seen when viewing Plan tab
    if (activeTab === 'plan') {
      lastSeenTopicsRef.current = executed;
      setPlanTabHasUpdate(false);
    }
  }, [executedTopics, activeTab, setPlanTabHasUpdate, toast]);

  const planViewState: PlanViewState = useMemo(() => {
    // =========================================================================
    // Setup → Plan transition logic
    // =========================================================================
    // Auto-transitions when tiles are available

    // Tiles path: If tiles exist, trust backend's plan_view_state
    if (
      hasTilesReady &&
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
  ]);

  // Auto-switch to Plan Mode when generation is in progress
  useEffect(() => {
    if (planViewState === 'S1_FRAMING') {
      if (!isDesktop) {
        switchToPlan(); // Mobile uses tab switching
      }
      // Desktop: Update activeView in store (drives GlassCommandBar)
      setActiveView('planning');
    }
  }, [isDesktop, planViewState, switchToPlan, setActiveView]);

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
    const backendPending = storeDocument?.pending_strategy_topics ?? [];
    // Use Map for stable deduplication (like Python's dict.fromkeys)
    return Array.from(
      new Map([...backendPending, ...localPendingTopics].map((t) => [t, true])).keys()
    );
  }, [storeDocument?.pending_strategy_topics, localPendingTopics]);

  // Plan View Model - populated from backend response via storeDocument
  const planViewModel: PlanViewModel = useMemo(() => {
    // DEBUG: Log when building view model
    console.log('[NomadicLanding] 🔄 Building planViewModel:', {
      strategy_sections_count: storeDocument?.strategy_sections?.length ?? 0,
      day_cards_count: storeDocument?.day_cards?.length ?? 0,
      plan_view_state: storeDocument?.plan_view_state,
      executed_strategy_topics: storeDocument?.executed_strategy_topics,
    });
    return {
      strategy_sections: storeDocument?.strategy_sections,
      executed_strategy_topics: storeDocument?.executed_strategy_topics,
      pending_strategy_topics: mergedPendingTopics,
      open_decisions: storeDocument?.open_decisions ?? [],
      itinerary_overview: storeDocument?.itinerary_overview ?? undefined,
      day_cards: storeDocument?.day_cards,
      itinerary_assumptions: storeDocument?.itinerary_assumptions ?? undefined,
      needs_refresh: storeDocument?.needs_refresh,
      can_expand_to_itinerary: storeDocument?.can_expand_to_itinerary,
    };
  }, [storeDocument, mergedPendingTopics]);

  // Merged generation state: envelope wins if present, else local UI fallback
  const envelopeGeneration = storeDocument?.generation as GenerationState | undefined;
  const generation: GenerationState | null = useMemo(() => {
    if (envelopeGeneration) return envelopeGeneration;
    if (uiGeneration) return uiGeneration;
    // Derive from isGenerating flag when no explicit generation state
    if (isGenerating) return { active: true, stage: 'structure' as const };
    return null;
  }, [envelopeGeneration, uiGeneration, isGenerating]);

  // Tiles from document store
  const tiles = storeDocument?.tiles ?? {};

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
        switchToPlan(); // Mobile uses tab switching
      }
      setActiveView('planning');
    }
  }, [hasDates, canViewPlan, activeView, isDesktop, switchToPlan, setActiveView]);

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
  const proceedWithItineraryGeneration = useCallback(async () => {
    // Generate runId for this generation (also serves as idempotency key)
    const runId = crypto.randomUUID();

    // Start generation in documentStore - gets AbortController and registers runId
    const abortController = documentStore.startGeneration(runId);

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
      // Get current document state for context
      const currentDoc = documentStore.document;
      const preferredTileIds = documentStore.preferredTileIds;

      // Build preferences from heart state
      const tiles = currentDoc?.tiles ?? {};
      const preferredHotelIds: string[] = [];
      const preferredActivityIds: string[] = [];

      // Debug: Log raw preference state BEFORE categorization
      console.log('[expand-itinerary] 💜 Raw preferences:', {
        preferredTileIds: Array.from(preferredTileIds),
        preferredTileIds_size: preferredTileIds.size,
        tilesKeys: Object.keys(tiles).slice(0, 5),
        tilesCount: Object.keys(tiles).length,
      });

      // Categorize preferred tiles by type (handle various type variants)
      for (const tileId of preferredTileIds) {
        const tile = tiles[tileId];
        const tileType = (tile?.type || '').toLowerCase();
        console.log('[expand-itinerary] 💜 Processing tile:', {
          tileId,
          found: !!tile,
          type: tileType,
          title: tile?.title?.substring(0, 30),
        });
        if (tile) {
          // Match hotel variants
          if (tileType === 'hotel' || tileType === 'stay' || tileType === 'accommodation') {
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

      // Debug: Log what we're sending
      console.log('[expand-itinerary] 📤 Final preferences payload:', {
        preferred_hotel_ids: preferredHotelIds,
        preferred_activity_ids: preferredActivityIds,
        will_send: preferredHotelIds.length > 0 || preferredActivityIds.length > 0,
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
          console.debug('[expand-itinerary] Merging envelope with day_cards:', event.plan_envelope?.day_cards?.length);
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
        } else if (event.type === 'error') {
          console.error('[expand-itinerary] Error received:', event.message);
          setLastGenerationError(event.message || 'Failed to generate itinerary');
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
      if (documentStore.isCurrentRun(runId)) {
        setUiGeneration(null);
      }
    }
  }, [storeDocument, shortlist.savedTileIds, documentStore]);

  // Handler for expanding to itinerary - validation gates before generation
  // "Assume & Refine" philosophy: Backend auto-selects recommended stay if none saved
  const handleExpandToItinerary = useCallback(async () => {
    // GATE 0: Don't expand if plan is currently regenerating (race condition prevention)
    if (isRegenerating) {
      addToast('Plan is updating, please wait...', 'info');
      return;
    }

    const currentTripInputs = storeDocument?.trip_inputs;

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
    // Backend auto-selects recommended stay if none saved (no modal needed)
    await proceedWithItineraryGeneration();
  }, [storeDocument, addToast, proceedWithItineraryGeneration, isRegenerating]);

  // Handle quick pick from InlineDatePrompt
  const handleSelectNights = useCallback(
    async (nights: number) => {
      const startDate = storeDocument?.trip_inputs?.start_date;
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
    [storeDocument?.trip_inputs?.start_date, addDaysUTC, documentStore, addToast]
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

  // Handler for minimized chat input (Plan/Book tabs) - sends message via ChatPanel
  const handleMinimizedSendMessage = useCallback((message: string) => {
    chatPanelRef.current?.sendMessage?.(message);
  }, []);

  // Stage navigation handlers for interactive stepper tabs
  // Setup: Navigate to Setup view (only allowed before planning)
  const handleSetupClick = useCallback(() => {
    // If plan exists, Setup is locked - show confirmation dialog as fallback
    if (hasLeftSetup) {
      setSetupConfirmDialogOpen(true);
    } else {
      // No plan yet - navigate to Setup view
      navigateTo('setup');
      if (!isDesktop) {
        switchToPlanner();
      }
    }
  }, [hasLeftSetup, navigateTo, isDesktop, switchToPlanner]);

  // Confirmed setup action - open sheet for editing (Setup is locked after planning)
  const handleConfirmedSetupNavigation = useCallback(() => {
    // Open destination sheet for editing core constraints
    openSheet('destination');
    setSetupConfirmDialogOpen(false);
  }, [openSheet]);

  // Plan: Navigate to Plan view
  const handlePlanClick = useCallback(() => {
    if (navigateTo('plan')) {
      if (!isDesktop) {
        switchToPlan();
      }
    }
  }, [navigateTo, isDesktop, switchToPlan]);

  // Book: Navigate to Book view
  const handleBookClick = useCallback(() => {
    if (navigateTo('book')) {
      if (!isDesktop) {
        // Mobile: switch to book tab (handled by MobileModeContext sync)
      }
    }
  }, [navigateTo, isDesktop]);

  // Compute minimum selections for Book stage gating (1 flight + 1 hotel)
  const hasMinimumSelections = useMemo(() => {
    const savedTiles = Array.from(shortlist.savedTileIds);
    const hasHotel = savedTiles.some((id) => {
      const tile = tiles[id];
      return tile?.type === 'hotel' || tile?.type === 'stay';
    });
    const hasFlight = savedTiles.some((id) => {
      const tile = tiles[id];
      return tile?.type === 'flight';
    });
    return hasHotel && hasFlight;
  }, [shortlist.savedTileIds, tiles]);

  // Planner content (left panel): ChatPanel (primary funnel with refinements inside)
  const plannerContent = (
    <ChatPanel
      ref={chatPanelRef}
      key={chatKey}
      selectedBranchId={selectedBranchId}
      onPlanResult={handlePlanResultWithReceipt}
      onGeneratePlanStart={handleGeneratePlanStartWithSnapshot}
      onFreshStart={handleStartNewSession}
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
            ? `${formatDateForDisplay(tripInputs.start_date)} → ?`  // Incomplete state
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
      onSetupClick={handleSetupClick}
      onPlanClick={handlePlanClick}
      onBookClick={handleBookClick}
      hasMinimumSelections={hasMinimumSelections}
      isRegenerating={isRegenerating}
      onSelectNights={handleSelectNights}
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
          bookContent={
            <BookingSection
              state={planViewState}
              tiles={tiles}
              generation={generation}
              hasStrategyContent={hasStrategyContent}
              savedTileIds={shortlist.savedTileIds}
              onSaveTile={shortlist.toggleItem}
              onOpenSheet={openSheet}
              strategySections={storeDocument?.strategy_sections}
            />
          }
          planState={planState}
          hasDestination={hasDestination}
          onReset={handleStartNewSession}
          onSendMessage={handleMinimizedSendMessage}
          isProcessing={isGenerating}
          planTabEnabled={planTabEnabled}
          bookTabEnabled={bookTabEnabled}
          // Mobile Plan Footer CTA props
          hasDates={hasDates}
          showCta={planViewState === 'S2_STRATEGY_READY'}
          onBuildItinerary={handleExpandToItinerary}
          onSelectDates={() => openSheet('dates')}
          headerContent={
            <div className="flex w-full items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <Compass className="text-primary h-5 w-5" />
                  <span className="text-foreground text-lg font-semibold">Nomadic</span>
                </div>
                <span className="text-muted-foreground/50 hidden text-sm sm:inline">
                  <span className="text-muted-foreground/30 mx-2">|</span>
                  Change your mind. Keep the plan.
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleStartNewSession}
                className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:text-zinc-500 dark:hover:text-white dark:hover:bg-white/5"
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
      </div>

      {/* Destructive action confirmation - when clicking Setup from Plan/Book */}
      <ConfirmDialog
        isOpen={setupConfirmDialogOpen}
        onClose={() => setSetupConfirmDialogOpen(false)}
        onConfirm={handleConfirmedSetupNavigation}
        title="Edit trip details?"
        description="Changing dates or destination will reset your current itinerary. Any saved selections will need to be re-added."
        confirmLabel="Edit Details"
        cancelLabel="Keep Plan"
        variant="destructive"
      />

      {/* Trip input sheets - shared between header pills and chat panel */}
      {/* In S1+, header pills are the ONLY interactive surface for trip inputs */}
      <DestinationSheet
        open={activeSheet === 'destination'}
        onOpenChange={(open) => !open && closeSheet()}
        value={tripInputs.destination || ''}
        onSave={async (value) => {
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
          await documentStore.commitTripInputs({
            start_date: startStr,
            end_date: endStr,
          });
          closeSheet();
          // Toast is already shown by DatesSheet, no need for duplicate
        }}
      />

      <TravelersSheet
        open={activeSheet === 'travelers'}
        onOpenChange={(open) => !open && closeSheet()}
        adults={tripInputs.adults ?? 1}
        children={tripInputs.children ?? 0}
        onSave={async (adults, children) => {
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
    </>
  );
}

// Inner component that uses MobileModeContext (for StartupSequence)
function AppWithStartup() {
  const [hasBooted, setHasBooted] = useState(false);

  return (
    <>
      {!hasBooted && <StartupSequence onComplete={() => setHasBooted(true)} />}
      <div
        className={
          hasBooted
            ? 'opacity-100 transition-opacity duration-300'
            : 'opacity-0'
        }
      >
        <NomadicLanding />
      </div>
    </>
  );
}

// Wrap the component with MobileModeProvider
export default function NomadicLandingWithProvider() {
  return (
    <MobileModeProvider>
      <AppWithStartup />
    </MobileModeProvider>
  );
}
