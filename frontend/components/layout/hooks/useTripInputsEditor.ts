/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { validateTripInput } from '@/lib/api';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';

const SUPPORTED_CURRENCIES = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY'] as const;
type SupportedCurrency = (typeof SUPPORTED_CURRENCIES)[number];

type TripInputsDraft = {
  destination: string | null;
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  adults?: string | null;
  children?: string | null;
  requires_assistance?: boolean | null;
  budget?: string | null;
  currency?: string | null;
};

const toTripInputsDraft = (inputs: DocumentTripInputs): TripInputsDraft => ({
  destination: inputs.destination ?? null,
  origin: inputs.origin ?? null,
  start_date: inputs.start_date ?? null,
  end_date: inputs.end_date ?? null,
  adults: inputs.adults != null ? String(inputs.adults) : null,
  children: inputs.children != null ? String(inputs.children) : null,
  requires_assistance: inputs.requires_assistance ?? null,
  budget: inputs.budget != null ? String(inputs.budget) : null,
  currency: inputs.currency ?? 'USD',
});

interface TripInputsEditorOptions {
  tripInputs: DocumentTripInputs;
  storeTripInputs: DocumentTripInputs | null | undefined;
  onToast: (message: string, type?: ToastType) => void;
}

interface ValidationError {
  field: 'origin' | 'destination';
  message: string;
}

interface TripInputsEditorState {
  tripInputsDraft: TripInputsDraft;
  editingField: keyof TripInputsDraft | null;
  selectedLocationBadge: 'origin' | number | null;
  destinationInput: string;
  destinationInputExpanded: boolean;
  originInput: string;
  originInputExpanded: boolean;
  // Validation state
  validationLoading: 'origin' | 'destination' | null;
  // Pending values shown during validation (not persisted)
  pendingOrigin: string | null;
  pendingDestination: string | null;
  // Inline validation error for display below fields
  validationError: ValidationError | null;
}

interface TripInputsEditorActions {
  setTripInputsDraft: React.Dispatch<React.SetStateAction<TripInputsDraft>>;
  setEditingField: React.Dispatch<React.SetStateAction<keyof TripInputsDraft | null>>;
  setSelectedLocationBadge: React.Dispatch<React.SetStateAction<'origin' | number | null>>;
  setDestinationInput: React.Dispatch<React.SetStateAction<string>>;
  setDestinationInputExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  setOriginInput: React.Dispatch<React.SetStateAction<string>>;
  setOriginInputExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  handleStartEditingField: (field: keyof TripInputsDraft) => void;
  handleFieldChange: (field: keyof TripInputsDraft, value: string) => void;
  handleCommitField: (field?: keyof TripInputsDraft, value?: string) => Promise<void>;
  handleSetOrigin: (origin: string) => Promise<void>;
  handleRemoveOrigin: () => Promise<void>;
  handleRemoveTravelers: () => Promise<void>;
  handleUpdateAdults: (value: number | null) => void;
  handleUpdateChildren: (value: number | null) => void;
  handleToggleRequiresAssistance: () => Promise<void>;
  handleRemoveBudget: () => Promise<void>;
  handleUpdateCurrency: (currency: string) => Promise<void>;
  /** @deprecated Multi-city feature removed */
  handleToggleMultiCity: () => Promise<void>;
  handleAddDestination: (destination: string) => Promise<void>;
  handleRemoveDestination: () => Promise<void>;
  clearValidationError: () => void;
  resetDraft: () => void;
}

type UseTripInputsEditorReturn = TripInputsEditorState & TripInputsEditorActions;

export function useTripInputsEditor(
  options: TripInputsEditorOptions
): UseTripInputsEditorReturn {
  const { tripInputs, storeTripInputs, onToast } = options;

  const commitTripInputs = useDocumentStore((s) => s.commitTripInputs);
  const updateTripInputs = useDocumentStore((s) => s.updateTripInputs);

  // Draft state for UI editing (kept local)
  const [tripInputsDraft, setTripInputsDraft] = useState<TripInputsDraft>(() =>
    toTripInputsDraft(DEFAULT_TRIP_INPUTS)
  );

  const [editingField, setEditingField] = useState<keyof TripInputsDraft | null>(null);
  const [selectedLocationBadge, setSelectedLocationBadge] = useState<'origin' | number | null>(null);
  const [destinationInput, setDestinationInput] = useState('');
  const [destinationInputExpanded, setDestinationInputExpanded] = useState(false);
  const [originInput, setOriginInput] = useState('');
  const [originInputExpanded, setOriginInputExpanded] = useState(false);

  // Validation state
  const [validationLoading, setValidationLoading] = useState<'origin' | 'destination' | null>(null);
  // Pending values shown during validation (not persisted, discarded on rejection)
  const [pendingOrigin, setPendingOrigin] = useState<string | null>(null);
  const [pendingDestination, setPendingDestination] = useState<string | null>(null);
  // Inline validation error for display below fields
  const [validationError, setValidationError] = useState<ValidationError | null>(null);

  // Sync tripInputsDraft when store trip_inputs changes
  // Always sync destinations (they're modified by bot, not inline editing)
  // Only skip other fields if user is actively editing them
  useEffect(() => {
    if (!storeTripInputs) return;

    setTripInputsDraft((prev) => {
      // Always update destination from store (source of truth)
      // This ensures bot-initiated changes are reflected in UI
      const newDraft: TripInputsDraft = {
        ...prev,
        destination: storeTripInputs.destination ?? null,
      };

      // Only update other fields if not actively editing
      if (editingField === null) {
        newDraft.origin = storeTripInputs.origin ?? null;
        newDraft.start_date = storeTripInputs.start_date ?? null;
        newDraft.end_date = storeTripInputs.end_date ?? null;
        newDraft.adults = storeTripInputs.adults != null
          ? String(storeTripInputs.adults)
          : null;
        newDraft.children = storeTripInputs.children != null
          ? String(storeTripInputs.children)
          : null;
        newDraft.requires_assistance = storeTripInputs.requires_assistance ?? null;
        newDraft.budget = storeTripInputs.budget != null
          ? String(storeTripInputs.budget)
          : null;
        newDraft.currency = storeTripInputs.currency ?? newDraft.currency ?? 'USD';
      }

      return newDraft;
    });
  }, [storeTripInputs, editingField]);

  const handleStartEditingField = useCallback((field: keyof TripInputsDraft) => {
    setEditingField(field);
  }, []);

  const handleFieldChange = useCallback((field: keyof TripInputsDraft, value: string) => {
    setTripInputsDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
  }, []);

  const handleCommitField = useCallback(
    async (field?: keyof TripInputsDraft, value?: string) => {
      setEditingField(null);

      if (!field) return;

      const prevValue = tripInputs[field as keyof DocumentTripInputs];
      const trimmedValue = value?.trim();

      // If the user cleared the field, restore the previous value and don't commit
      if (!trimmedValue) {
        setTripInputsDraft((prev) => {
          if (!prev) return prev;
          return { ...prev, [field]: prevValue ?? '' };
        });
        return;
      }

      // For numeric fields, validate the value
      let parsedValue: string | number = trimmedValue;
      if (field === 'adults' || field === 'children') {
        const count = parseInt(trimmedValue, 10);
        if (Number.isNaN(count) || count < 0) {
          setTripInputsDraft((prev) => ({
            ...toTripInputsDraft(tripInputs),
            ...prev,
            [field]: prevValue != null ? String(prevValue) : '',
          }));
          return;
        }
        parsedValue = count;
      } else if (field === 'budget') {
        const budget = parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (Number.isNaN(budget) || budget <= 0) {
          setTripInputsDraft((prev) => ({
            ...toTripInputsDraft(tripInputs),
            ...prev,
            budget: prevValue != null ? String(prevValue) : '',
          }));
          return;
        }
        parsedValue = budget;
      } else if (field === 'currency') {
        const currency = trimmedValue.toUpperCase();
        if (!SUPPORTED_CURRENCIES.includes(currency as SupportedCurrency)) {
          setTripInputsDraft((prev) => ({
            ...toTripInputsDraft(tripInputs),
            ...prev,
            currency: prevValue != null ? String(prevValue) : '',
          }));
          onToast('Unsupported currency. Please pick another option.', 'error');
          return;
        }
        parsedValue = currency;
      }

      // Don't commit if value hasn't changed
      if (trimmedValue === String(prevValue ?? '')) {
        return;
      }

      // Update draft locally
      setTripInputsDraft((prev) => {
        const base = prev ?? toTripInputsDraft(tripInputs);
        return { ...base, [field]: trimmedValue };
      });

      // Commit to document store
      const updates: Record<string, string | number | null> = {};
      if (field === 'origin') {
        updates.origin = trimmedValue;
      } else if (field === 'adults') {
        updates.adults = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue, 10);
      } else if (field === 'children') {
        updates.children = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue, 10);
      } else if (field === 'budget') {
        updates.budget = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
      } else if (field === 'currency') {
        updates.currency = typeof parsedValue === 'string' ? parsedValue.toUpperCase() : trimmedValue.toUpperCase();
      }

      const success = await commitTripInputs(updates);

      if (!success) {
        onToast(`Failed to update ${field.replace('_', ' ')}. Please try again.`, 'error');
        return;
      }

      // Add assistant message to acknowledge the change
      let message: string | null = null;

      if (field === 'origin') {
        message = `Got it! Departing from ${trimmedValue}. ✈️`;
      } else if (field === 'budget') {
        const budget = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (!Number.isNaN(budget) && budget > 0) {
          message = `Got it! Budget set to $${budget.toLocaleString()}. 💰`;
        }
      } else if (field === 'currency' && typeof parsedValue === 'string') {
        message = `Updated currency to ${parsedValue}. 💱`;
      }

      if (message) {
        onToast(message, 'confirmation');
      }
    },
    [tripInputs, commitTripInputs, onToast]
  );

  const handleSetOrigin = useCallback(
    async (origin: string) => {
      const trimmedOrigin = origin.trim();
      if (!trimmedOrigin) return;

      // Clear any previous validation error for this field
      setValidationError(null);

      // Show pending value immediately (not stored anywhere)
      setPendingOrigin(trimmedOrigin);
      setOriginInput('');

      // Start validation
      setValidationLoading('origin');

      try {
        const result = await validateTripInput('origin', trimmedOrigin);

        if (!result.is_valid) {
          // Invalid origin - discard pending value and show inline error
          setPendingOrigin(null);
          const errorMsg = result.reason || 'This doesn\'t appear to be a valid location.';
          setValidationError({ field: 'origin', message: errorMsg });
          onToast(`Invalid origin: ${errorMsg}`, 'error');
          setValidationLoading(null);
          return;
        }

        // Auto-apply correction if provided
        const correctedValue = result.corrected_values[0];
        const valueToCommit = correctedValue || trimmedOrigin;
        const success = await commitTripInputs({ origin: valueToCommit });

        if (!success) {
          setPendingOrigin(null);
          onToast('Failed to set origin. Please try again.', 'error');
          setValidationLoading(null);
          return;
        }

        // Clear pending value (now stored in document)
        setPendingOrigin(null);
        setValidationLoading(null);

        onToast(`Origin set: ${valueToCommit}`, 'confirmation');
      } catch {
        setPendingOrigin(null);
        onToast('Validation failed. Please try again.', 'error');
        setValidationLoading(null);
      }
    },
    [commitTripInputs, onToast]
  );

  const handleRemoveOrigin = useCallback(async () => {
    const removedOrigin = tripInputs.origin;
    if (!removedOrigin) {
      setSelectedLocationBadge(null);
      return;
    }

    // Optimistically update via commitTripInputs
    const success = await commitTripInputs({ origin: null });

    if (!success) {
      onToast('Failed to remove origin. Please try again.', 'error');
      return;
    }

    // Add confirmation toast to acknowledge the removal
    onToast(`Origin removed: ${removedOrigin}`, 'confirmation');

    setSelectedLocationBadge(null);
  }, [tripInputs.origin, commitTripInputs, onToast]);

  const handleRemoveTravelers = useCallback(async () => {
    if (tripInputs.adults == null && tripInputs.children == null && tripInputs.requires_assistance == null) return;

    const success = await commitTripInputs({
      adults: null,
      children: null,
      requires_assistance: null,
    });

    if (!success) {
      onToast('Failed to clear travelers. Please try again.', 'error');
      return;
    }

    onToast('Cleared the travelers info. 👥', 'confirmation');
  }, [tripInputs.adults, tripInputs.children, tripInputs.requires_assistance, commitTripInputs, onToast]);

  // Refs for debouncing travelers updates to prevent rapid API calls
  const pendingTravelersUpdate = useRef<{ adults?: number | null; children?: number | null }>({});
  const travelersDebounceTimer = useRef<NodeJS.Timeout | null>(null);

  // Ref to store previous destination for race-safe revert on validation failure
  const prevDestinationRef = useRef<string | null>(null);

  // Debounced commit function for travelers
  const commitTravelersUpdate = useCallback(async () => {
    const updates = pendingTravelersUpdate.current;
    if (Object.keys(updates).length === 0) return;

    pendingTravelersUpdate.current = {};

    const success = await commitTripInputs(updates);
    if (!success) {
      onToast('Failed to update travelers. Please try again.', 'error');
    }
  }, [commitTripInputs, onToast]);

  const handleUpdateAdults = useCallback((value: number | null) => {
    pendingTravelersUpdate.current.adults = value;

    if (travelersDebounceTimer.current) {
      clearTimeout(travelersDebounceTimer.current);
    }
    travelersDebounceTimer.current = setTimeout(commitTravelersUpdate, 300);
  }, [commitTravelersUpdate]);

  const handleUpdateChildren = useCallback((value: number | null) => {
    pendingTravelersUpdate.current.children = value;

    if (travelersDebounceTimer.current) {
      clearTimeout(travelersDebounceTimer.current);
    }
    travelersDebounceTimer.current = setTimeout(commitTravelersUpdate, 300);
  }, [commitTravelersUpdate]);

  const handleToggleRequiresAssistance = useCallback(async () => {
    const newValue = !tripInputs.requires_assistance;
    const success = await commitTripInputs({ requires_assistance: newValue });
    if (!success) {
      onToast('Failed to update assistance setting. Please try again.', 'error');
      return;
    }
    const message = newValue
      ? 'Noted! Will look for accessibility options. ♿'
      : 'Removed accessibility requirement.';
    onToast(message, 'confirmation');
  }, [tripInputs.requires_assistance, commitTripInputs, onToast]);

  const handleRemoveBudget = useCallback(async () => {
    if (tripInputs.budget == null) return;

    const success = await commitTripInputs({ budget: null });

    if (!success) {
      onToast('Failed to clear budget. Please try again.', 'error');
      return;
    }

    onToast('Cleared the budget. 💰', 'confirmation');
  }, [tripInputs.budget, commitTripInputs, onToast]);

  const handleUpdateCurrency = useCallback(async (currency: string) => {
    const normalized = currency.toUpperCase();
    if (!SUPPORTED_CURRENCIES.includes(normalized as SupportedCurrency)) {
      onToast('Unsupported currency. Please pick another option.', 'error');
      return;
    }

    // Optimistically update draft
    setTripInputsDraft((prev) => ({ ...prev, currency: normalized }));

    const success = await commitTripInputs({ currency: normalized });
    if (!success) {
      onToast('Failed to update currency. Please try again.', 'error');
    }
  }, [commitTripInputs, onToast]);

  // TODO: multi_city_intent feature is not yet implemented in DocumentTripInputs type
  const handleToggleMultiCity = useCallback(async () => {
    // Stubbed - multi_city_intent not in type yet
    onToast('Multi-city feature coming soon!', 'confirmation');
  }, [onToast]);

  const handleAddDestination = useCallback(
    async (destination: string) => {
      const trimmedDestination = destination.trim();
      if (!trimmedDestination) return;

      // Clear any previous validation error for this field
      setValidationError(null);

      // Capture previous value BEFORE update (for race-safe revert)
      prevDestinationRef.current = tripInputs.destination ?? null;

      // SYNC: Write to store immediately (before validation)
      // This ensures RefreshButton sees the new value instantly
      updateTripInputs({ destination: trimmedDestination });

      // Clear pending/input state
      setPendingDestination(null);
      setDestinationInput('');

      // Validate in background (revert if invalid)
      setValidationLoading('destination');

      try {
        const result = await validateTripInput('destination', trimmedDestination);

        if (!result.is_valid) {
          // Invalid destination - revert store to captured previous value (race-safe)
          updateTripInputs({ destination: prevDestinationRef.current });
          const errorMsg = result.reason || 'This doesn\'t appear to be a valid destination.';
          setValidationError({ field: 'destination', message: errorMsg });
          onToast(`Invalid destination: ${errorMsg}`, 'error');
          setValidationLoading(null);
          return;
        }

        // Apply correction if needed
        const correctedValue = result.corrected_values[0] || trimmedDestination;
        if (correctedValue !== trimmedDestination) {
          updateTripInputs({ destination: correctedValue });
        }

        // Persist to backend
        const success = await commitTripInputs({ destination: correctedValue });

        if (!success) {
          onToast('Failed to set destination. Please try again.', 'error');
          setValidationLoading(null);
          return;
        }

        setValidationLoading(null);
        onToast(`Destination set to "${correctedValue}" 📍`, 'confirmation');
      } catch {
        // Revert on error
        updateTripInputs({ destination: prevDestinationRef.current });
        onToast('Validation failed. Please try again.', 'error');
        setValidationLoading(null);
      }
    },
    [tripInputs.destination, commitTripInputs, updateTripInputs, onToast]
  );

  const handleRemoveDestination = useCallback(
    async () => {
      const currentDestination = tripInputs.destination;
      if (!currentDestination) return;

      // Clear the destination
      const success = await commitTripInputs({ destination: null });

      if (!success) {
        onToast('Failed to clear destination. Please try again.', 'error');
        return;
      }

      onToast(`Cleared destination "${currentDestination}". 📍`, 'confirmation');
      setSelectedLocationBadge(null);
    },
    [tripInputs.destination, commitTripInputs, onToast]
  );

  const resetDraft = useCallback(() => {
    setTripInputsDraft(toTripInputsDraft(DEFAULT_TRIP_INPUTS));
    setEditingField(null);
    setSelectedLocationBadge(null);
    setDestinationInput('');
    setDestinationInputExpanded(false);
    setOriginInput('');
    setOriginInputExpanded(false);
    // Reset validation state
    setValidationLoading(null);
    // Reset pending values
    setPendingOrigin(null);
    setPendingDestination(null);
    // Reset validation errors
    setValidationError(null);
  }, []);

  return {
    // State
    tripInputsDraft,
    editingField,
    selectedLocationBadge,
    destinationInput,
    destinationInputExpanded,
    originInput,
    originInputExpanded,
    // Validation state
    validationLoading,
    // Pending values (shown during validation)
    pendingOrigin,
    pendingDestination,
    // Inline validation error
    validationError,
    clearValidationError: () => setValidationError(null),
    // State setters
    setTripInputsDraft,
    setEditingField,
    setSelectedLocationBadge,
    setDestinationInput,
    setDestinationInputExpanded,
    setOriginInput,
    setOriginInputExpanded,
    // Handlers
    handleStartEditingField,
    handleFieldChange,
    handleCommitField,
    handleSetOrigin,
    handleRemoveOrigin,
    handleRemoveTravelers,
    handleUpdateAdults,
    handleUpdateChildren,
    handleToggleRequiresAssistance,
    handleRemoveBudget,
    handleUpdateCurrency,
    handleToggleMultiCity,
    handleAddDestination,
    handleRemoveDestination,
    resetDraft,
  };
}
