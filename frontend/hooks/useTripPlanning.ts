/**
 * Compound Hook for Trip Planning
 *
 * Consolidates the 4 main hooks used in NomadicLanding into a single
 * structured return object. This reduces prop drilling by allowing
 * components to receive a single `tripPlanning` object instead of
 * 60+ individual props.
 *
 * Hooks consolidated:
 * - useBranchManager: Branch and tile management
 * - useTripInputsEditor: Trip input editing state
 * - useDateRangeSelector: Calendar and date selection
 * - useLocalBookingSettings: Booking preferences
 */

import { useEffect, useRef } from 'react';

import { useBranchManager } from '@/components/layout/hooks/useBranchManager';
import { useDateRangeSelector } from '@/components/layout/hooks/useDateRangeSelector';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';

// =============================================================================
// Types
// =============================================================================

export type UseTripPlanningOptions = {
  /** Trip inputs from document store */
  tripInputs: DocumentTripInputs;
  /** Raw store trip inputs (for dirty checking) */
  storeTripInputs: DocumentTripInputs | undefined;
  /** Toast notification function */
  onToast: (message: string, type?: ToastType) => void;
  /** Chat key increment function (for resetting chat) */
  onChatKeyIncrement: () => void;
  /** Ref to chat panel container for scroll behavior */
  chatPanelContainerRef: React.RefObject<HTMLDivElement | null>;
};

// =============================================================================
// Hook
// =============================================================================

export function useTripPlanning({
  tripInputs,
  storeTripInputs,
  onToast,
  onChatKeyIncrement,
  chatPanelContainerRef,
}: UseTripPlanningOptions) {
  // Keep a ref to tripInputsEditor for the branchManager resetDraft callback
  const tripInputsEditorRef = useRef<ReturnType<typeof useTripInputsEditor> | null>(null);

  // ─────────────────────────────────────────────────────────────────────────
  // Booking Settings Hook
  // ─────────────────────────────────────────────────────────────────────────
  const bookingSettings = useLocalBookingSettings(storeTripInputs, onToast);

  // ─────────────────────────────────────────────────────────────────────────
  // Branch Manager Hook
  // ─────────────────────────────────────────────────────────────────────────
  const branchManager = useBranchManager({
    tripInputs,
    chatPanelContainerRef,
    onToast,
    onChatKeyIncrement,
    resetDraft: () => tripInputsEditorRef.current?.resetDraft(),
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Trip Inputs Editor Hook
  // ─────────────────────────────────────────────────────────────────────────
  const tripInputsEditor = useTripInputsEditor({
    tripInputs,
    storeTripInputs,
    onToast,
  });

  // Update ref after tripInputsEditor is created (must be in useEffect, not during render)
  useEffect(() => {
    tripInputsEditorRef.current = tripInputsEditor;
  }, [tripInputsEditor]);

  // ─────────────────────────────────────────────────────────────────────────
  // Date Range Selector Hook
  // ─────────────────────────────────────────────────────────────────────────
  const dateRangeSelector = useDateRangeSelector({
    tripInputs,
    tripInputsDraft: tripInputsEditor.tripInputsDraft,
    setTripInputsDraft: tripInputsEditor.setTripInputsDraft,
    onToast,
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Computed Values
  // ─────────────────────────────────────────────────────────────────────────
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination = Boolean(tripInputs.destination);
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);
  const hasDates = hasStartDate || hasEndDate;
  const missingFields = tripInputs.missing_fields ?? [];

  // ─────────────────────────────────────────────────────────────────────────
  // Return Structured Object
  // ─────────────────────────────────────────────────────────────────────────
  return {
    // Sub-hook results (for direct access when needed)
    branchManager,
    tripInputsEditor,
    dateRangeSelector,
    bookingSettings,

    // Computed values for convenience
    computed: {
      hasOrigin,
      hasDestination,
      hasStartDate,
      hasEndDate,
      hasDates,
      missingFields,
    },

    // Flattened frequently used values for less nesting
    branches: branchManager.branches,
    selectedBranchId: branchManager.selectedBranchId,
    isGenerating: branchManager.isGenerating,
    readyToGenerate: branchManager.readyToGenerate,
    hasBranchesReady: branchManager.hasBranchesReady,
    tripInputsDraft: tripInputsEditor.tripInputsDraft,
    editingField: tripInputsEditor.editingField,
    calendarOpen: dateRangeSelector.calendarOpen,
    selectedDateRange: dateRangeSelector.selectedDateRange,
  };
}

export type UseTripPlanningReturn = ReturnType<typeof useTripPlanning>;

// =============================================================================
// Props Builder for TripDetailsForm
// =============================================================================

/**
 * Builds the props object for TripDetailsForm from useTripPlanning return.
 * This helper reduces boilerplate when passing props to the form.
 */
export function buildTripDetailsFormProps(
  planning: UseTripPlanningReturn,
  tripInputs: DocumentTripInputs,
  datePresets: Array<{ label: string; getDates: () => { from: Date; to: Date } }>,
  llmUpdatedFields: Set<string>,
  onAcknowledgeLLMUpdate: (field: string) => void
) {
  const { tripInputsEditor, dateRangeSelector, bookingSettings, computed } = planning;

  return {
    // Trip inputs data
    tripInputs,
    tripInputsDraft: tripInputsEditor.tripInputsDraft,
    editingField: tripInputsEditor.editingField,

    // Computed flags
    hasOrigin: computed.hasOrigin,
    hasDestination: computed.hasDestination,
    hasDates: computed.hasDates,
    hasStartDate: computed.hasStartDate,
    hasEndDate: computed.hasEndDate,

    // Calendar state
    calendarOpen: dateRangeSelector.calendarOpen,
    selectedDateRange: dateRangeSelector.selectedDateRange,
    previewDays: dateRangeSelector.previewDays,
    hasDateValidationWarning: dateRangeSelector.hasDateValidationWarning,

    // Location state
    selectedLocationBadge: tripInputsEditor.selectedLocationBadge,
    originInput: tripInputsEditor.originInput,
    originInputExpanded: tripInputsEditor.originInputExpanded,
    destinationInput: tripInputsEditor.destinationInput,
    destinationInputExpanded: tripInputsEditor.destinationInputExpanded,
    pendingOrigin: tripInputsEditor.pendingOrigin,
    pendingDestination: tripInputsEditor.pendingDestination,
    validationError: tripInputsEditor.validationError,

    // Date presets
    datePresets,

    // Validation error handlers
    onClearValidationError: tripInputsEditor.clearValidationError,

    // Field editing handlers
    onStartEditingField: tripInputsEditor.handleStartEditingField,
    onFieldChange: tripInputsEditor.handleFieldChange,
    onCommitField: tripInputsEditor.handleCommitField,
    setTripInputsDraft: tripInputsEditor.setTripInputsDraft,
    setEditingField: tripInputsEditor.setEditingField,

    // Origin handlers
    onSetOrigin: tripInputsEditor.handleSetOrigin,
    onRemoveOrigin: tripInputsEditor.handleRemoveOrigin,
    setOriginInput: tripInputsEditor.setOriginInput,
    setOriginInputExpanded: tripInputsEditor.setOriginInputExpanded,

    // Destination handlers
    onAddDestination: tripInputsEditor.handleAddDestination,
    onRemoveDestination: tripInputsEditor.handleRemoveDestination,
    setDestinationInput: tripInputsEditor.setDestinationInput,
    setDestinationInputExpanded: tripInputsEditor.setDestinationInputExpanded,
    onToggleMultiCity: tripInputsEditor.handleToggleMultiCity,

    // Calendar handlers
    onCalendarOpenChange: dateRangeSelector.handleCalendarOpenChange,
    onCalendarDayClick: dateRangeSelector.handleCalendarDayClick,
    onCalendarDayMouseEnter: dateRangeSelector.handleCalendarDayMouseEnter,
    onCalendarMouseLeave: dateRangeSelector.handleCalendarMouseLeave,
    onDatePresetClick: dateRangeSelector.handleDatePresetClick,
    onResetDates: dateRangeSelector.handleResetDates,

    // Traveler handlers
    onRemoveTravelers: tripInputsEditor.handleRemoveTravelers,
    onUpdateAdults: tripInputsEditor.handleUpdateAdults,
    onUpdateChildren: tripInputsEditor.handleUpdateChildren,
    onToggleRequiresAssistance: tripInputsEditor.handleToggleRequiresAssistance,

    // Budget handlers
    onRemoveBudget: tripInputsEditor.handleRemoveBudget,
    onUpdateCurrency: tripInputsEditor.handleUpdateCurrency,

    // Location badge handler
    onSelectLocationBadge: tripInputsEditor.setSelectedLocationBadge,

    // Booking settings
    bookingTypes: bookingSettings.bookingTypes,
    flightSettings: bookingSettings.flightSettings,
    hotelSettings: bookingSettings.hotelSettings,
    activitySettings: bookingSettings.activitySettings,
    transportSettings: bookingSettings.transportSettings,
    onUpdateBookingTypes: bookingSettings.handleUpdateBookingTypes,
    onUpdateFlightSettings: bookingSettings.handleUpdateFlightSettings,
    onUpdateHotelSettings: bookingSettings.handleUpdateHotelSettings,
    onUpdateActivitySettings: bookingSettings.handleUpdateActivitySettings,
    onUpdateTransportSettings: bookingSettings.handleUpdateTransportSettings,
    onAddActivity: bookingSettings.handleAddActivity,
    onRemoveActivity: bookingSettings.handleRemoveActivity,

    // LLM update tracking
    llmUpdatedFields,
    onAcknowledgeLLMUpdate,
  };
}
