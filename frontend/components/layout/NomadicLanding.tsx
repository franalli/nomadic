'use client';

// date-fns imports removed - no longer needed after TripDetailsForm removal
import { AnimatePresence, motion } from 'framer-motion';
import { Compass, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import {
  type PlanResultPayload,
  useBranchManager,
} from '@/components/layout/hooks/useBranchManager';
import { useDateRangeSelector } from '@/components/layout/hooks/useDateRangeSelector';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import { FloatingBuildButton } from '@/components/layout/FloatingBuildButton';
import { SetupDrawer } from '@/components/layout/SetupDrawer';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import { useSpecialistDeepLink } from '@/hooks/useSpecialistDeepLink';
import type { SpecialistType } from '@/lib/specialistLinkParser';
import { BookingSection } from '@/components/plan/BookingSection';
import { ConfirmStaySheet } from '@/components/plan/ConfirmStaySheet';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { TripLengthSheet } from '@/components/plan/TripLengthSheet';
import {
  BudgetSheet,
  DatesSheet,
  DestinationSheet,
  OriginSheet,
  TravelersSheet,
} from '@/components/planner/sheets';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { MobileModeProvider, useMobileMode } from '@/contexts/MobileModeContext';
import { useSheetManager } from '@/hooks/useSheetManager';
import { useShortlist } from '@/hooks/useShortlist';
import { apiFetch, fetchDestinationImage } from '@/lib/api';
import { createStreamParser, type StreamEvent } from '@/lib/streamParser';
import { filterTilesByType } from '@/lib/tileSelectors';
import { formatDateForDisplay } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER } from '@/state/chatStore';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import { isBookingEnabled, type DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanState, PlanViewModel,PlanViewState } from '@/types/plan-envelope';

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
    .filter(([_, keywords]) => keywords.some(k => lower.includes(k)))
    .map(([topic]) => topic);
}

// Toast notification system
const MAX_TOASTS = 3;
const TOAST_DISMISS_MS = 4000;
const TOAST_DISMISS_FAST_MS = 2000;
const TOAST_DISMISS_ERROR_MS = 5000;
const TOAST_DISMISS_CONFIRMATION_MS = 2500;

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  createdAt: number;
}

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
  const {
    isDesktop,
    switchToPlan,
    switchToPlanner,
    activeTab,
    setPlanTabHasUpdate,
  } = useMobileMode();

  // Document store - single source of truth for trip inputs
  const documentStore = useDocumentStore();
  const storeTripInputs = documentStore.document?.trip_inputs;
  const llmUpdatedFields = documentStore.llmUpdatedFields;
  const acknowledgeLLMUpdate = documentStore.acknowledgeLLMUpdate;
  const restoreTripInputs = documentStore.restoreTripInputs;
  const isCommitting = documentStore.isCommitting;

  // Sheet manager - shared between header pills and chat panel
  // In S1+, header pills are the only interactive surface for trip inputs
  const { activeSheet, openSheet, closeSheet } = useSheetManager();

  // Receipt state - shows "Updated: X, Y · Undo" after freeform extraction
  // Kept for future receipt UI implementation
  const [_receiptData, setReceiptData] = useState<ChangeReceiptData | null>(null);
  const previousTripInputsRef = useRef<DocumentTripInputs | null>(null);

  // Track if we've ever had a plan to prevent regression to Setup mode
  // Once a plan is generated, we stay in Plan mode (never revert to S0_BOOTSTRAP)
  // Using state (not ref) so changes trigger re-renders and useMemo re-computation
  const [hasEverHadPlan, setHasEverHadPlan] = useState(false);

  // Track if user explicitly requested plan generation (clicked "Build Plan")
  // This prevents Plan tab from showing prematurely when backend sends data
  const [userRequestedGeneration, setUserRequestedGeneration] = useState(false);

  // Optimistic pending topics - detected from user messages before backend responds
  // Used to show placeholder AgentCards immediately while backend processes
  const [localPendingTopics, setLocalPendingTopics] = useState<string[]>([]);

  // Derive tripInputs from store (with defaults)
  const tripInputs: DocumentTripInputs = useMemo(() => {
    if (!storeTripInputs) return DEFAULT_TRIP_INPUTS;
    return { ...DEFAULT_TRIP_INPUTS, ...storeTripInputs };
  }, [storeTripInputs]);

  // Toast notification state - supports multiple stacked toasts
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastIdRef = useRef(0);

  // Local UI generation state (fallback if backend doesn't emit generation in envelope)
  const [uiGeneration, setUiGeneration] = useState<GenerationState | null>(null);
  const [lastGenerationError, setLastGenerationError] = useState<string | null>(null);

  // Add a toast with optional type (defaults to 'info')
  // Confirmation toasts coalesce (replace existing confirmations) to avoid stacking rapid changes
  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = `toast-${++toastIdRef.current}`;
    const newToast: Toast = { id, message, type, createdAt: Date.now() };

    setToasts((prev) => {
      // For confirmation toasts, replace any existing confirmation instead of stacking
      if (type === 'confirmation') {
        const withoutConfirmations = prev.filter((t) => t.type !== 'confirmation');
        return [...withoutConfirmations, newToast];
      }
      // For other types, apply max limit
      const updated = prev.length >= MAX_TOASTS ? prev.slice(1) : prev;
      return [...updated, newToast];
    });
  }, []);

  // Remove a specific toast by ID
  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

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
    handleUpdateActivitySettings: _handleUpdateActivitySettings,
    handleAddActivity,
    handleRemoveActivity,
  } = useLocalBookingSettings(storeTripInputs, addToast);

  // Shortlist hook - manages user's saved tiles in S2
  const shortlist = useShortlist();

  // Sheet states for itinerary validation flow
  const [tripLengthSheetOpen, setTripLengthSheetOpen] = useState(false);
  const [confirmStaySheetOpen, setConfirmStaySheetOpen] = useState(false);

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
    branches,
    selectedBranchId,
    isGenerating,
    readyToGenerate,
    hasBranchesReady,
    setBranches,
    setSelectedBranchId,
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
    // Close any open sheets (validation + trip input sheets)
    setTripLengthSheetOpen(false);
    setConfirmStaySheetOpen(false);
    closeSheet(); // Close any open trip input sheet
    // Reset mobile mode to planner view (shows chat/setup)
    if (!isDesktop) {
      switchToPlanner();
    }
    // Proceed with branch manager reset (clears server session, chat, branches, etc.)
    await branchManagerStartNewSession();
  }, [shortlist, branchManagerStartNewSession, closeSheet, documentStore, isDesktop, switchToPlanner]);

  // Wrapped handlers for receipt functionality
  // Snapshot trip inputs before generation starts + switch to Plan Mode on mobile
  const handleGeneratePlanStartWithSnapshot = useCallback(() => {
    previousTripInputsRef.current = storeTripInputs ? { ...storeTripInputs } : null;
    setUserRequestedGeneration(true); // Track explicit user request for Plan tab
    handleGeneratePlanStart();
    // Switch to Plan Mode on mobile when generation starts
    if (!isDesktop) {
      switchToPlan();
    }
  }, [storeTripInputs, handleGeneratePlanStart, isDesktop, switchToPlan]);

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
  const handleUserMessageSubmit = useCallback((message: string) => {
    if (!hasEverHadPlan) return; // Only do optimistic UI after first plan

    const detectedTopics = detectTopicsFromMessage(message);
    // Use documentStore.document directly to avoid variable scope issues
    const existingTopics = new Set(documentStore.document?.executed_strategy_topics ?? []);
    const newTopics = detectedTopics.filter(t => !existingTopics.has(t));

    if (newTopics.length > 0) {
      setLocalPendingTopics(prev => {
        // Stable deduplication using Map
        return Array.from(
          new Map([...prev, ...newTopics].map(t => [t, true])).keys()
        );
      });
    }
  }, [hasEverHadPlan, documentStore.document?.executed_strategy_topics]);

  // Receipt undo/dismiss handlers removed - re-add when receipt UI is implemented
  // Uses: previousTripInputsRef, storeTripInputs, restoreTripInputs, setReceiptData, detectChangedFieldNames
  void restoreTripInputs; // Silence unused variable warning

  // Trip inputs editor hook - manages all trip input editing state and handlers
  const tripInputsEditor = useTripInputsEditor({
    tripInputs,
    storeTripInputs,
    branches,
    selectedBranchId,
    onBranchesChange: setBranches,
    onSelectedBranchIdChange: setSelectedBranchId,
    onToast: addToast,
  });

  // Update ref after tripInputsEditor is created (must be in useEffect, not during render)
  useEffect(() => {
    tripInputsEditorRef.current = tripInputsEditor;
  }, [tripInputsEditor]);

  // Destructure commonly used values from the hook
  // Note: resetDraft is accessed via tripInputsEditorRef.current in branchManager callback
  const {
    tripInputsDraft,
    setTripInputsDraft,
    handleFieldChange: _handleFieldChange,
    handleCommitField: _handleCommitField,
    handleUpdateAdults,
    handleUpdateChildren,
    handleToggleRequiresAssistance,
    handleUpdateCurrency: _handleUpdateCurrency,
    // Unused after TripDetailsForm removal - kept for potential future use
    editingField: _editingField,
    selectedLocationBadge: _selectedLocationBadge,
    destinationInput: _destinationInput,
    destinationInputExpanded: _destinationInputExpanded,
    originInput: _originInput,
    originInputExpanded: _originInputExpanded,
    pendingOrigin: _pendingOrigin,
    pendingDestination: _pendingDestination,
    validationError: _validationError,
    clearValidationError: _clearValidationError,
    setEditingField: _setEditingField,
    setSelectedLocationBadge: _setSelectedLocationBadge,
    setDestinationInput: _setDestinationInput,
    setDestinationInputExpanded: _setDestinationInputExpanded,
    setOriginInput: _setOriginInput,
    setOriginInputExpanded: _setOriginInputExpanded,
    handleStartEditingField: _handleStartEditingField,
    handleSetOrigin: _handleSetOrigin,
    handleRemoveOrigin: _handleRemoveOrigin,
    handleRemoveTravelers: _handleRemoveTravelers,
    handleRemoveBudget: _handleRemoveBudget,
    handleToggleMultiCity: _handleToggleMultiCity,
    handleAddDestination: _handleAddDestination,
    handleRemoveDestination: _handleRemoveDestination,
  } = tripInputsEditor;

  // Date range selector hook - manages calendar state and date selection
  const dateRangeSelector = useDateRangeSelector({
    tripInputs,
    tripInputsDraft,
    setTripInputsDraft,
    onToast: addToast,
  });

  // Destructure commonly used values from the date range hook
  // Note: Currently unused after TripDetailsForm removal, kept for potential future use
  const {
    calendarOpen: _calendarOpen,
    selectedDateRange: _selectedDateRange,
    previewDays: _previewDays,
    hasDateValidationWarning: _hasDateValidationWarning,
    handleCalendarDayClick: _handleCalendarDayClick,
    handleCalendarDayMouseEnter: _handleCalendarDayMouseEnter,
    handleCalendarMouseLeave: _handleCalendarMouseLeave,
    handleCalendarOpenChange: _handleCalendarOpenChange,
    handleDatePresetClick: _handleDatePresetClick,
    handleResetDates: _handleResetDates,
  } = dateRangeSelector;

  // Toast auto-dismiss effect - handles multiple toasts with different timings
  useEffect(() => {
    if (toasts.length === 0) return undefined;

    const timers: NodeJS.Timeout[] = [];

    toasts.forEach((toast, index) => {
      // Calculate dismiss time based on type and queue position
      let dismissTime = TOAST_DISMISS_MS;
      if (toast.type === 'error') {
        dismissTime = TOAST_DISMISS_ERROR_MS;
      } else if (toast.type === 'confirmation') {
        dismissTime = TOAST_DISMISS_CONFIRMATION_MS;
      } else if (toasts.length >= MAX_TOASTS && index === 0) {
        // Oldest toast when queue is full dismisses faster
        dismissTime = TOAST_DISMISS_FAST_MS;
      }

      const elapsed = Date.now() - toast.createdAt;
      const remaining = Math.max(0, dismissTime - elapsed);

      const timer = setTimeout(() => {
        removeToast(toast.id);
      }, remaining);
      timers.push(timer);
    });

    return () => {
      timers.forEach((timer) => clearTimeout(timer));
    };
  }, [toasts, removeToast]);

  const missingFields = tripInputs.missing_fields ?? [];

  // Check if we have origin or destination to show route
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination = Boolean(tripInputs.destination);
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);

  // NEW: Derive plan state envelope fields
  // Use backend-provided plan_state if available, otherwise derive from local state
  const storeDocument = documentStore.document;
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
              const date = new Date(tripInputs.start_date);
              const formatted = date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
              });
              parts.push(formatted);
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
  // V1: branches + strategy content
  // V2: tiles (branches are empty in V2)
  // Using state ensures useMemo re-computes when this changes
  const hasTilesReady = Object.keys(storeDocument?.tiles ?? {}).length > 0;
  useEffect(() => {
    // V1 path: branches + strategy
    if (hasBranchesReady && hasStrategyContent && !hasEverHadPlan && userRequestedGeneration) {
      setHasEverHadPlan(true);
    }
    // V2 path: tiles exist (even without explicit Build Plan click)
    if (hasTilesReady && !hasEverHadPlan) {
      setHasEverHadPlan(true);
    }
  }, [hasBranchesReady, hasStrategyContent, hasEverHadPlan, userRequestedGeneration, hasTilesReady]);

  // Clear local pending topics when backend responds with executed_strategy_topics
  // Topics that appear in executed are successfully processed
  // Topics that were pending but didn't execute stay (backend didn't process them)
  const executedTopics = storeDocument?.executed_strategy_topics ?? [];
  useEffect(() => {
    if (executedTopics.length > 0) {
      setLocalPendingTopics(prev =>
        prev.filter(topic => !executedTopics.includes(topic))
      );
    }
  }, [executedTopics]);

  // Badge notification: Track when specialists update (for Plan tab badge on mobile)
  const lastSeenTopicsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const executed = new Set(executedTopics);
    const hasNew = [...executed].some(t => !lastSeenTopicsRef.current.has(t));
    // Show badge when new topics executed AND user is not on Plan tab
    if (hasNew && activeTab !== 'plan') {
      setPlanTabHasUpdate(true);
    }
    // Update last seen when viewing Plan tab
    if (activeTab === 'plan') {
      lastSeenTopicsRef.current = executed;
      setPlanTabHasUpdate(false);
    }
  }, [executedTopics, activeTab, setPlanTabHasUpdate]);

  const planViewState: PlanViewState = useMemo(() => {
    // =========================================================================
    // Setup → Plan transition logic
    // =========================================================================
    // V1: Requires explicit "Build Plan" click
    // V2: Auto-transitions when tiles are available

    // V2 path: If tiles exist, trust backend's plan_view_state
    if (hasTilesReady && backendPlanViewState && backendPlanViewState !== 'S0_BOOTSTRAP') {
      return backendPlanViewState;
    }

    // V1 path: Before user clicks "Build Plan", stay in Setup mode
    if (!hasEverHadPlan && !userRequestedGeneration && !hasTilesReady) {
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
  }, [backendPlanViewState, isGenerating, hasStrategyContent, hasEverHadPlan, userRequestedGeneration, hasTilesReady]);

  // Auto-switch to Plan Mode when generation is in progress (mobile only)
  useEffect(() => {
    if (!isDesktop && planViewState === 'S1_FRAMING') {
      switchToPlan();
    }
  }, [isDesktop, planViewState, switchToPlan]);

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
      new Map([...backendPending, ...localPendingTopics].map(t => [t, true])).keys()
    );
  }, [storeDocument?.pending_strategy_topics, localPendingTopics]);

  // Plan View Model - populated from backend response via storeDocument
  const planViewModel: PlanViewModel = useMemo(() => {
    // DEBUG: Log strategy sections when building view model
    console.log('[NomadicLanding] Building planViewModel:', {
      strategy_sections_count: storeDocument?.strategy_sections?.length ?? 0,
      strategy_sections: storeDocument?.strategy_sections,
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

  // Fallback title from tripInputs (used when destinationCard not yet available)
  const fallbackTitle = tripInputs.destination ?? undefined;

  // CTA gating flags per strict render contract
  // hasDates: at least start_date OR flexible dates with duration
  const hasDates =
    Boolean(tripInputs.start_date) ||
    (tripInputs.date_flex === true && tripInputs.trip_duration != null);
  const canGeneratePlan = hasDestination && hasDates;
  const hasPlan = hasBranchesReady;

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
          setUiGeneration({ active: true, stage: 'itinerary', message: 'Still working...' });
        }
      }, STREAM_TIMEOUT_MS);
    };

    resetTimeout();

    try {
      const response = await apiFetch('/v1/expand-itinerary', {
        method: 'POST',
        body: JSON.stringify({
          idempotency_key: runId,
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

        if (event.type === 'envelope') {
          documentStore.mergeEnvelope(event.plan_envelope);
        } else if (event.type === 'progress') {
          setUiGeneration({
            active: true,
            stage: event.stage,
            message: event.message,
            pct: event.pct,
          });
        } else if (event.type === 'done') {
          setUiGeneration(null);
          setLastGenerationError(null);
        } else if (event.type === 'error') {
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
  const handleExpandToItinerary = useCallback(async () => {
    const currentTripInputs = storeDocument?.trip_inputs;
    const currentTiles = storeDocument?.tiles ?? {};
    const currentBookingTypes = currentTripInputs?.booking_types;

    // GATE 1: Check for duration (end_date OR trip_duration - no date_flex requirement)
    const hasDuration = !!currentTripInputs?.end_date || currentTripInputs?.trip_duration != null;
    if (!hasDuration) {
      // Only open TripLengthSheet if we have a start date
      if (!currentTripInputs?.start_date) {
        addToast('Set a start date first', 'info');
        return;
      }
      setTripLengthSheetOpen(true);
      return;
    }

    // GATE 2: If Stays ON, check for stay selection (tri-state: suggested or on = enabled)
    const staysEnabled = isBookingEnabled(currentBookingTypes?.hotels);
    const stayTiles = filterTilesByType(currentTiles, 'stay');
    const hasSavedStay = stayTiles.some(t => shortlist.savedTileIds.has(t.id));

    if (staysEnabled) {
      // No stay tiles exist - need to generate plan first
      if (stayTiles.length === 0) {
        addToast('Build a plan first to see stay options', 'info');
        return;
      }
      // Need selection - open ConfirmStaySheet
      if (!hasSavedStay) {
        setConfirmStaySheetOpen(true);
        return;
      }
    }

    // All gates passed - proceed with itinerary generation (no override needed)
    await proceedWithItineraryGeneration();
  }, [storeDocument, shortlist.savedTileIds, addToast, proceedWithItineraryGeneration]);

  // Handle quick pick from TripLengthSheet
  const handleSelectNights = useCallback(async (nights: number) => {
    const startDate = storeDocument?.trip_inputs?.start_date;
    if (!startDate) return;

    // Calculate end date (timezone-safe)
    const endDateStr = addDaysUTC(startDate, nights);

    // Update trip inputs and await confirmation
    const success = await documentStore.commitTripInputs({ end_date: endDateStr });

    // Close sheet
    setTripLengthSheetOpen(false);

    // Only proceed if store update succeeded
    if (success) {
      // Call directly - store is already updated
      handleExpandToItinerary();
    }
  }, [storeDocument?.trip_inputs?.start_date, addDaysUTC, documentStore, handleExpandToItinerary]);

  // Handle "Use recommended" from ConfirmStaySheet
  const handleUseRecommendedStay = useCallback(async () => {
    // Close sheet first
    setConfirmStaySheetOpen(false);

    // Proceed with itinerary generation
    await proceedWithItineraryGeneration();
  }, [proceedWithItineraryGeneration]);

  // Handle "Choose a stay" from ConfirmStaySheet
  const handleChooseStay = useCallback(() => {
    setConfirmStaySheetOpen(false);
    // Switch to stays tab if on mobile, or scroll to stays section
    // TODO: Implement navigation to stays section
  }, []);

  // Handler for viewing booking options (scroll to section)
  const handleViewBookingOptions = useCallback(() => {
    document.getElementById('booking-section')?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  // Handler for "Build plan" CTA in right panel (S0BootstrapView)
  // Triggers plan generation via ChatPanel
  const handleBuildPlan = useCallback(() => {
    chatPanelRef.current?.sendMessage?.(GENERATE_PLAN_TRIGGER);
  }, []);

  // Handler for minimized chat input (Plan/Book tabs) - sends message via ChatPanel
  const handleMinimizedSendMessage = useCallback((message: string) => {
    chatPanelRef.current?.sendMessage?.(message);
  }, []);

  // Stage navigation handlers for interactive stepper tabs
  // Setup: scroll to configuration or open sheet
  const handleSetupClick = useCallback(() => {
    // If plan exists, show confirmation dialog (destructive action warning)
    if (hasEverHadPlan) {
      setSetupConfirmDialogOpen(true);
    } else {
      // No plan yet - scroll to left panel (chat)
      document.getElementById('chat-panel')?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [hasEverHadPlan]);

  // Confirmed setup action - actually navigate to setup/config
  const handleConfirmedSetupNavigation = useCallback(() => {
    // Open destination sheet for editing core constraints
    openSheet('destination');
    setSetupConfirmDialogOpen(false);
  }, [openSheet]);

  // Plan: scroll to plan view (right panel)
  const handlePlanClick = useCallback(() => {
    document.getElementById('plan-panel')?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  // Book: scroll to booking section (bottom of right panel)
  const handleBookClick = useCallback(() => {
    document.getElementById('booking-section')?.scrollIntoView({ behavior: 'smooth' });
  }, []);

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
        hasStartDate || hasEndDate
          ? `${formatDateForDisplay(tripInputs.start_date)}${hasStartDate && hasEndDate ? ' - ' : ''}${formatDateForDisplay(tripInputs.end_date)}`
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
      onViewBookingOptions={handleViewBookingOptions}
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
    />
  );

  // Toast container elements - rendered outside .appTopo to avoid CSS conflicts
  const errorToasts = (
    <div
      style={{
        position: 'fixed',
        top: '16px',
        right: '16px',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: '8px',
      }}
    >
      <AnimatePresence mode="popLayout">
        {toasts
          .filter((t) => t.type === 'error')
          .map((toast) => (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: -50, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9, y: -20 }}
              transition={{
                type: 'spring',
                stiffness: 500,
                damping: 35,
                layout: { type: 'spring', stiffness: 500, damping: 35 },
              }}
              role="alert"
              aria-live="assertive"
              className="border-destructive/40 bg-destructive/5 dark:bg-destructive/20 text-destructive/70 flex items-center gap-3 rounded-lg border px-4 py-3 text-sm shadow-lg backdrop-blur-sm dark:text-red-200"
            >
              <span className="max-w-[260px] truncate sm:max-w-[320px]">
                {toast.message}
              </span>
              <button
                type="button"
                className="text-destructive/60 hover:text-destructive/50 text-xs font-semibold transition-colors dark:text-red-300/70 dark:hover:text-red-300"
                onClick={() => removeToast(toast.id)}
                aria-label="Dismiss notification"
              >
                ✕
              </button>
            </motion.div>
          ))}
      </AnimatePresence>
    </div>
  );

  const successToasts = (
    <div
      style={{
        position: 'fixed',
        top: 'auto',
        bottom: '24px',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '8px',
        pointerEvents: 'none',
      }}
    >
      <AnimatePresence mode="popLayout">
        {toasts
          .filter((t) => t.type !== 'error')
          .map((toast) => {
            const typeStyles: Record<string, string> = {
              success:
                'border-primary/30 bg-primary/5 dark:bg-primary/20 text-primary dark:text-primary-foreground',
              info: 'border-primary/30 bg-primary/5 dark:bg-primary/20 text-primary dark:text-primary-foreground',
              confirmation:
                'border-primary/20 bg-primary/5 dark:bg-primary/20 text-primary/80 dark:text-primary-foreground/90',
            };
            const buttonStyles: Record<string, string> = {
              success:
                'text-primary/50 hover:text-primary/70 dark:text-primary-foreground/60 dark:hover:text-primary-foreground',
              info: 'text-primary/50 hover:text-primary/70 dark:text-primary-foreground/60 dark:hover:text-primary-foreground',
              confirmation:
                'text-primary/40 hover:text-primary/60 dark:text-primary-foreground/50 dark:hover:text-primary-foreground/80',
            };

            return (
              <motion.div
                key={toast.id}
                layout
                initial={{ opacity: 0, y: 20, scale: 0.9 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9, y: 20 }}
                transition={{
                  type: 'spring',
                  stiffness: 500,
                  damping: 35,
                  layout: { type: 'spring', stiffness: 500, damping: 35 },
                }}
                role="status"
                aria-live="polite"
                style={{ pointerEvents: 'auto' }}
                className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm shadow-md backdrop-blur-sm ${typeStyles[toast.type] || typeStyles.info}`}
              >
                <span className="max-w-[280px] truncate sm:max-w-[360px]">
                  {toast.message}
                </span>
                <button
                  type="button"
                  className={`text-xs font-medium transition-colors ${buttonStyles[toast.type] || buttonStyles.info}`}
                  onClick={() => removeToast(toast.id)}
                  aria-label="Dismiss notification"
                >
                  ✕
                </button>
              </motion.div>
            );
          })}
      </AnimatePresence>
    </div>
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
            />
          }
          planState={planState}
          isSetupPhase={planViewState === 'S0_BOOTSTRAP'}
          hasDestination={hasDestination}
          onReset={handleStartNewSession}
          onSendMessage={handleMinimizedSendMessage}
          isProcessing={isGenerating}
          headerContent={
            <div className="flex w-full items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <Compass className="text-primary h-5 w-5" />
                  <span className="text-foreground text-lg font-semibold">Nomadic</span>
                </div>
                <span className="text-muted-foreground hidden text-sm sm:inline">
                  Change constraints. Keep the plan.
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleStartNewSession}
                className="text-muted-foreground hover:text-foreground"
              >
                <RotateCcw className="mr-1.5 h-4 w-4" />
                Reset
              </Button>
            </div>
          }
        />

        {/* Setup Drawer - mobile accordion for setup checklist */}
        <SetupDrawer
          onSetDestination={() => openSheet('destination')}
          onSetOrigin={() => openSheet('origin')}
          onSetDates={() => openSheet('dates')}
          onSetTravelers={() => openSheet('travelers')}
          onSetBudget={() => openSheet('budget')}
        />

        {/* Floating Build Button - mobile FAB for plan generation */}
        <FloatingBuildButton
          visible={readyToGenerate && planViewState === 'S0_BOOTSTRAP'}
          onClick={handleBuildPlan}
          isGenerating={isGenerating}
          hasEverHadPlan={hasEverHadPlan}
        />
      </div>

      {/* Toast containers - rendered outside .appTopo to avoid CSS conflicts */}
      {errorToasts}
      {successToasts}

      {/* Validation sheets for itinerary generation */}
      <TripLengthSheet
        open={tripLengthSheetOpen}
        onOpenChange={setTripLengthSheetOpen}
        startDate={storeDocument?.trip_inputs?.start_date ?? null}
        onSelectNights={handleSelectNights}
        onOpenDatePicker={() => {
          setTripLengthSheetOpen(false);
          // Delay to let TripLengthSheet close animation finish
          setTimeout(() => openSheet('dates'), 150);
        }}
      />

      <ConfirmStaySheet
        open={confirmStaySheetOpen}
        onOpenChange={setConfirmStaySheetOpen}
        onUseRecommended={handleUseRecommendedStay}
        onChooseStay={handleChooseStay}
      />

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
        startDate={tripInputs.start_date ? new Date(tripInputs.start_date) : null}
        endDate={tripInputs.end_date ? new Date(tripInputs.end_date) : null}
        onSave={async (start, end) => {
          const startStr = start.toISOString().slice(0, 10);
          const endStr = end.toISOString().slice(0, 10);
          await documentStore.commitTripInputs({ start_date: startStr, end_date: endStr });
          closeSheet();
          const startFormatted = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
          const endFormatted = end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
          addToast(`Dates: ${startFormatted}–${endFormatted}`, 'confirmation');
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
        onSave={async (amount, currency, _budgetType) => {
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

// Wrap the component with MobileModeProvider
export default function NomadicLandingWithProvider() {
  return (
    <MobileModeProvider>
      <NomadicLanding />
    </MobileModeProvider>
  );
}
