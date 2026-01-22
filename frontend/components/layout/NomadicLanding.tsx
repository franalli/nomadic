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
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import { ConfirmStaySheet } from '@/components/plan/ConfirmStaySheet';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { TripLengthSheet } from '@/components/plan/TripLengthSheet';
import { Button } from '@/components/ui/button';
import { MobileModeProvider, useMobileMode } from '@/contexts/MobileModeContext';
import { useShortlist } from '@/hooks/useShortlist';
import { createStreamParser, type StreamEvent } from '@/lib/streamParser';
import { filterTilesByType } from '@/lib/tileSelectors';
import { formatDateForDisplay } from '@/lib/utils';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanState, PlanViewModel,PlanViewState } from '@/types/plan-envelope';

// Receipt data type for showing "Updated: X, Y · Undo" after freeform extraction
interface ChangeReceiptData {
  type: 'partial' | 'updated' | 'reverted';
  fields: string[];
  canUndo: boolean;
}

// Trip context selections for itinerary generation
// Used to deterministically build context from saved OR recommended items
interface TripContextSelections {
  selected_stay_id?: string;
  selected_flight_id?: string;
  selected_activity_ids?: string[];
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
  if (
    JSON.stringify(oldInputs?.destinations) !== JSON.stringify(newInputs.destinations) &&
    (newInputs.destinations?.length ?? 0) > 0
  ) {
    changed.push('destinations');
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
  const { isDesktop, switchToPlan } = useMobileMode();

  // Document store - single source of truth for trip inputs
  const documentStore = useDocumentStore();
  const storeTripInputs = documentStore.document?.trip_inputs;
  const llmUpdatedFields = documentStore.llmUpdatedFields;
  const acknowledgeLLMUpdate = documentStore.acknowledgeLLMUpdate;
  const restoreTripInputs = documentStore.restoreTripInputs;

  // Receipt state - shows "Updated: X, Y · Undo" after freeform extraction
  // Kept for future receipt UI implementation
  const [_receiptData, setReceiptData] = useState<ChangeReceiptData | null>(null);
  const previousTripInputsRef = useRef<DocumentTripInputs | null>(null);

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

  // Branch manager hook - manages branches, tiles, and generating state
  const branchManager = useBranchManager({
    tripInputs,
    chatPanelContainerRef,
    chatPanelRef,
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
    handleStartNewSession,
    handlePlanResult,
    handleGeneratePlanStart,
  } = branchManager;

  // Wrapped handlers for receipt functionality
  // Snapshot trip inputs before generation starts + switch to Plan Mode on mobile
  const handleGeneratePlanStartWithSnapshot = useCallback(() => {
    previousTripInputsRef.current = storeTripInputs ? { ...storeTripInputs } : null;
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
  const hasDestination = (tripInputs.destinations ?? []).length > 0;
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
  const destinationCard =
    storeDocument?.destination_card ??
    (hasDestination
      ? {
          title: tripInputs.destinations?.[0] ?? '',
          subtitle: (() => {
            const parts: string[] = [];
            // Add origin → destination if we have origin
            if (tripInputs.origin) {
              parts.push(`${tripInputs.origin} → ${tripInputs.destinations?.[0] ?? ''}`);
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
              : `Trip to ${tripInputs.destinations?.[0] ?? ''}`;
          })(),
        }
      : undefined);

  // Booking status (from backend, for per-tab display) - kept for future booking UI

  // Plan View State (for StrategyStageRenderer)
  // Use backend's plan_view_state if available, otherwise derive locally
  const backendPlanViewState = storeDocument?.plan_view_state;
  const hasStrategyContent = (storeDocument?.strategy_sections?.length ?? 0) > 0;

  const planViewState: PlanViewState = useMemo(() => {
    // During generation, show loading state
    if (isGenerating) return 'S1_FRAMING';

    // Use backend-provided state when available
    if (backendPlanViewState) return backendPlanViewState;

    // Fallback: derive from local state
    if (!hasDestination) return 'S0_BOOTSTRAP';

    // Branches exist - determine S2 sub-state based on strategy content
    if (hasBranchesReady) {
      // Has strategy content = ready, otherwise still loading/blocked
      return hasStrategyContent ? 'S2_STRATEGY_READY' : 'S2_BLOCKED';
    }

    return 'S0_BOOTSTRAP';
  }, [backendPlanViewState, hasDestination, isGenerating, hasBranchesReady, hasStrategyContent]);

  // Auto-switch to Plan Mode when generation is in progress (mobile only)
  useEffect(() => {
    if (!isDesktop && planViewState === 'S1_FRAMING') {
      switchToPlan();
    }
  }, [isDesktop, planViewState, switchToPlan]);

  // Plan View Model - populated from backend response via storeDocument
  const planViewModel: PlanViewModel = useMemo(() => ({
    strategy_sections: storeDocument?.strategy_sections,
    open_decisions: storeDocument?.open_decisions ?? [],
    itinerary_overview: storeDocument?.itinerary_overview ?? undefined,
    day_cards: storeDocument?.day_cards,
    itinerary_assumptions: storeDocument?.itinerary_assumptions ?? undefined,
    needs_refresh: storeDocument?.needs_refresh,
    can_expand_to_itinerary: storeDocument?.can_expand_to_itinerary,
  }), [storeDocument]);

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
  const fallbackTitle = tripInputs.destinations?.[0] ?? undefined;

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
  const proceedWithItineraryGeneration = useCallback(async (
    override?: Partial<TripContextSelections>
  ) => {
    const currentTiles = storeDocument?.tiles ?? {};
    const currentTripInputs = storeDocument?.trip_inputs;
    const currentBookingTypes = currentTripInputs?.booking_types;
    const savedTileIds = shortlist.savedTileIds;

    // Build selections respecting enabled modules
    const staysEnabled = currentBookingTypes?.hotels !== false;
    const flightsEnabled = currentBookingTypes?.flights !== false;
    const activitiesEnabled = currentBookingTypes?.activities !== false;

    // Select stay: override > first saved > first recommended
    let selectedStayId: string | undefined;
    if (staysEnabled) {
      const stayTiles = filterTilesByType(currentTiles, 'stay');
      selectedStayId = override?.selected_stay_id
        ?? stayTiles.find(t => savedTileIds.has(t.id))?.id
        ?? stayTiles[0]?.id;
    }

    // Select flight: override > first saved > first recommended (only if enabled)
    let selectedFlightId: string | undefined;
    if (flightsEnabled) {
      const flightTiles = filterTilesByType(currentTiles, 'flight');
      selectedFlightId = override?.selected_flight_id
        ?? flightTiles.find(t => savedTileIds.has(t.id))?.id
        ?? flightTiles[0]?.id;
    }

    // Select activities: override > all saved > top 3 recommended (only if enabled)
    let selectedActivityIds: string[] | undefined;
    if (activitiesEnabled) {
      const activityTiles = filterTilesByType(currentTiles, 'activity');
      if (override?.selected_activity_ids) {
        selectedActivityIds = override.selected_activity_ids;
      } else {
        const savedActivities = activityTiles.filter(t => savedTileIds.has(t.id));
        selectedActivityIds = savedActivities.length > 0
          ? savedActivities.map(a => a.id)
          : activityTiles.slice(0, 3).map(a => a.id);
      }
    }

    // Build trip_context
    const tripContext: TripContextSelections = {
      ...(selectedStayId && { selected_stay_id: selectedStayId }),
      ...(selectedFlightId && { selected_flight_id: selectedFlightId }),
      ...(selectedActivityIds?.length && { selected_activity_ids: selectedActivityIds }),
    };

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
      const response = await fetch('/api/v1/expand-itinerary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idempotency_key: runId,
          trip_context: tripContext,
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

    // GATE 2: If Stays ON, check for stay selection
    const staysEnabled = currentBookingTypes?.hotels !== false;
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
  // CRITICAL: Pass override directly to avoid state race
  const handleUseRecommendedStay = useCallback(async () => {
    const currentTiles = storeDocument?.tiles ?? {};
    const firstStay = filterTilesByType(currentTiles, 'stay')[0];

    if (!firstStay) {
      addToast('No stays available', 'error');
      return;
    }

    // Close sheet first
    setConfirmStaySheetOpen(false);

    // Pass override directly to generation - no state race
    await proceedWithItineraryGeneration({ selected_stay_id: firstStay.id });
  }, [storeDocument?.tiles, proceedWithItineraryGeneration, addToast]);

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
      // Onboarding chips props - click handlers are internal to ChatPanel
      destination={tripInputs.destinations?.[0]}
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
      onExpandToItinerary={handleExpandToItinerary}
      onViewBookingOptions={handleViewBookingOptions}
      onReset={handleStartNewSession}
      lastError={lastGenerationError}
      onRetry={handleExpandToItinerary}
      savedTileIds={shortlist.savedTileIds}
      onSaveTile={shortlist.toggleItem}
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
        planState={planState}
        hasDestination={hasDestination}
        onReset={handleStartNewSession}
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
          // TODO: Open DatesSheet for custom date selection
        }}
      />

      <ConfirmStaySheet
        open={confirmStaySheetOpen}
        onOpenChange={setConfirmStaySheetOpen}
        onUseRecommended={handleUseRecommendedStay}
        onChooseStay={handleChooseStay}
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
