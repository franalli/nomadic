'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  toTripInputsDraft,
  type TripInputsDraft,
} from '@/components/layout/TripDetailsForm';
import { validateTripInput } from '@/lib/api';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch, DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';

const SUPPORTED_CURRENCIES = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY'] as const;
type SupportedCurrency = (typeof SUPPORTED_CURRENCIES)[number];

export interface TripInputsEditorOptions {
  tripInputs: DocumentTripInputs;
  storeTripInputs: DocumentTripInputs | null | undefined;
  branches: DocumentBranch[];
  selectedBranchId: string | null;
  onBranchesChange: (branches: DocumentBranch[]) => void;
  onSelectedBranchIdChange: (branchId: string | null) => void;
  onToast: (message: string, type?: ToastType) => void;
}

export interface ValidationError {
  field: 'origin' | 'destination';
  message: string;
}

export interface TripInputsEditorState {
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

export interface TripInputsEditorActions {
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
  handleToggleMultiCity: () => Promise<void>;
  handleAddDestination: (destination: string) => Promise<void>;
  handleRemoveDestination: (index: number) => Promise<void>;
  clearValidationError: () => void;
  resetDraft: () => void;
}

export type UseTripInputsEditorReturn = TripInputsEditorState & TripInputsEditorActions;

export function useTripInputsEditor(
  options: TripInputsEditorOptions
): UseTripInputsEditorReturn {
  const {
    tripInputs,
    storeTripInputs,
    branches,
    selectedBranchId,
    onBranchesChange,
    onSelectedBranchIdChange,
    onToast,
  } = options;

  const documentStore = useDocumentStore();

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
      // Always update destinations from store (source of truth)
      // This ensures bot-initiated changes are reflected in UI
      const newDraft: TripInputsDraft = {
        ...prev,
        destinations: storeTripInputs.destinations ?? [],
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

      const success = await documentStore.commitTripInputs(updates);

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
    [tripInputs, documentStore, onToast]
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
        const success = await documentStore.commitTripInputs({ origin: valueToCommit });

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
    [documentStore, onToast]
  );

  const handleRemoveOrigin = useCallback(async () => {
    const removedOrigin = tripInputs.origin;
    if (!removedOrigin) {
      setSelectedLocationBadge(null);
      return;
    }

    // Optimistically update via documentStore.commitTripInputs
    const success = await documentStore.commitTripInputs({ origin: null });

    if (!success) {
      onToast('Failed to remove origin. Please try again.', 'error');
      return;
    }

    // Add confirmation toast to acknowledge the removal
    onToast(`Origin removed: ${removedOrigin}`, 'confirmation');

    setSelectedLocationBadge(null);
  }, [tripInputs.origin, documentStore, onToast]);

  const handleRemoveTravelers = useCallback(async () => {
    if (tripInputs.adults == null && tripInputs.children == null && tripInputs.requires_assistance == null) return;

    const success = await documentStore.commitTripInputs({
      adults: null,
      children: null,
      requires_assistance: null,
    });

    if (!success) {
      onToast('Failed to clear travelers. Please try again.', 'error');
      return;
    }

    onToast('Cleared the travelers info. 👥', 'confirmation');
  }, [tripInputs.adults, tripInputs.children, tripInputs.requires_assistance, documentStore, onToast]);

  // Refs for debouncing travelers updates to prevent rapid API calls
  const pendingTravelersUpdate = useRef<{ adults?: number | null; children?: number | null }>({});
  const travelersDebounceTimer = useRef<NodeJS.Timeout | null>(null);

  // Debounced commit function for travelers
  const commitTravelersUpdate = useCallback(async () => {
    const updates = pendingTravelersUpdate.current;
    if (Object.keys(updates).length === 0) return;

    pendingTravelersUpdate.current = {};

    const success = await documentStore.commitTripInputs(updates);
    if (!success) {
      onToast('Failed to update travelers. Please try again.', 'error');
    }
  }, [documentStore, onToast]);

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
    const success = await documentStore.commitTripInputs({ requires_assistance: newValue });
    if (!success) {
      onToast('Failed to update assistance setting. Please try again.', 'error');
      return;
    }
    const message = newValue
      ? 'Noted! Will look for accessibility options. ♿'
      : 'Removed accessibility requirement.';
    onToast(message, 'confirmation');
  }, [tripInputs.requires_assistance, documentStore, onToast]);

  const handleRemoveBudget = useCallback(async () => {
    if (tripInputs.budget == null) return;

    const success = await documentStore.commitTripInputs({ budget: null });

    if (!success) {
      onToast('Failed to clear budget. Please try again.', 'error');
      return;
    }

    onToast('Cleared the budget. 💰', 'confirmation');
  }, [tripInputs.budget, documentStore, onToast]);

  const handleUpdateCurrency = useCallback(async (currency: string) => {
    const normalized = currency.toUpperCase();
    if (!SUPPORTED_CURRENCIES.includes(normalized as SupportedCurrency)) {
      onToast('Unsupported currency. Please pick another option.', 'error');
      return;
    }

    // Optimistically update draft
    setTripInputsDraft((prev) => ({ ...prev, currency: normalized }));

    const success = await documentStore.commitTripInputs({ currency: normalized });
    if (!success) {
      onToast('Failed to update currency. Please try again.', 'error');
    }
  }, [documentStore, onToast]);

  const handleToggleMultiCity = useCallback(async () => {
    const currentIntent = tripInputs.multi_city_intent;
    // Toggle: null/separate -> multi_city, multi_city -> separate
    const newIntent = currentIntent === 'multi_city' ? 'separate' : 'multi_city';

    const success = await documentStore.commitTripInputs({ multi_city_intent: newIntent });

    if (!success) {
      onToast('Failed to update trip style. Please try again.', 'error');
      return;
    }

    const message = newIntent === 'multi_city'
      ? 'Switched to one combined itinerary visiting all destinations! 🗺️'
      : 'Switched to separate plans for each destination! 📍';
    onToast(message, 'confirmation');
  }, [tripInputs.multi_city_intent, documentStore, onToast]);

  const handleAddDestination = useCallback(
    async (destination: string) => {
      const trimmedDestination = destination.trim();
      if (!trimmedDestination) return;

      const currentDestinations = tripInputs.destinations ?? [];

      // Clear any previous validation error for this field
      setValidationError(null);

      // Show pending value immediately (not stored anywhere)
      setPendingDestination(trimmedDestination);
      setDestinationInput('');

      // Start validation
      setValidationLoading('destination');

      try {
        const result = await validateTripInput('destination', trimmedDestination);

        if (!result.is_valid) {
          // Invalid destination - discard pending value and show inline error
          setPendingDestination(null);
          const errorMsg = result.reason || 'This doesn\'t appear to be a valid destination.';
          setValidationError({ field: 'destination', message: errorMsg });
          onToast(`Invalid destination: ${errorMsg}`, 'error');
          setValidationLoading(null);
          return;
        }

        // Auto-apply corrections (including multi-destination splits)
        const correctedValues = result.corrected_values;
        const wasSplit = correctedValues.length > 1;

        // Filter out duplicates and add all corrected values
        const newDestinations = [...currentDestinations];
        const addedDestinations: string[] = [];
        for (const dest of correctedValues) {
          if (!newDestinations.some((d) => d.toLowerCase() === dest.toLowerCase())) {
            newDestinations.push(dest);
            addedDestinations.push(dest);
          }
        }

        if (addedDestinations.length === 0) {
          setPendingDestination(null);
          setValidationLoading(null);
          return;
        }
        const success = await documentStore.commitTripInputs({ destinations: newDestinations });

        if (!success) {
          setPendingDestination(null);
          onToast('Failed to add destination. Please try again.', 'error');
          setValidationLoading(null);
          return;
        }

        // Clear pending value (now stored in document)
        setPendingDestination(null);
        setValidationLoading(null);

        // Show confirmation toast for added destinations
        if (wasSplit) {
          onToast(`Added ${addedDestinations.join(', ')} to your destinations! 📍`, 'confirmation');
        } else {
          onToast(`Added "${addedDestinations[0]}" to your destinations! 📍`, 'confirmation');
        }
      } catch {
        setPendingDestination(null);
        onToast('Validation failed. Please try again.', 'error');
        setValidationLoading(null);
      }
    },
    [tripInputs.destinations, documentStore, onToast]
  );

  const handleRemoveDestination = useCallback(
    async (index: number) => {
      const currentDestinations = tripInputs.destinations ?? [];
      if (index < 0 || index >= currentDestinations.length) return;

      // Get the destination being removed for the chat message
      const removedDestination = currentDestinations[index];

      // Compute new destinations array
      const newDestinations = currentDestinations.filter((_, i) => i !== index);

      // If we have branches, immediately prune any that include the removed destination
      if (branches.length > 0 && removedDestination) {
        const removedLower = removedDestination.toLowerCase();
        const prunedBranches = branches.filter((branch) => {
          // Keep branches that don't include the removed destination
          const branchDestinations = branch.destinations ?? [];
          return !branchDestinations.some(
            (d) => d.toLowerCase() === removedLower
          );
        });

        // If branches were pruned, update the UI immediately
        if (prunedBranches.length !== branches.length) {
          const removedCount = branches.length - prunedBranches.length;
          onBranchesChange(prunedBranches);

          // If all branches were removed, readyToGenerate will be computed automatically
          if (prunedBranches.length === 0) {
            onSelectedBranchIdChange(null);
            onToast(
              `Removed ${removedDestination} — your plan was reset. Click "Generate Plan" to create a new plan.`,
              'info'
            );
          } else {
            // Some branches remain - update selection if needed
            if (selectedBranchId && !prunedBranches.find((b) => b.id === selectedBranchId)) {
              const newSelectedId = prunedBranches.find((b) => b.is_primary)?.id ?? prunedBranches[0]?.id ?? null;
              onSelectedBranchIdChange(newSelectedId);
            }
            onToast(
              `Removed ${removedDestination} — ${removedCount} plan${removedCount > 1 ? 's were' : ' was'} updated.`,
              'info'
            );
          }
        }
      }

      // Optimistically update via documentStore.commitTripInputs
      // This updates the UI immediately and syncs to backend in background
      const success = await documentStore.commitTripInputs({ destinations: newDestinations });

      if (!success) {
        // Show error toast on failure (store already rolled back)
        onToast('Failed to remove destination. Please try again.', 'error');
        return;
      }

      // Add confirmation toast to acknowledge the removal
      if (removedDestination) {
        onToast(`Removed "${removedDestination}" from your destinations. 📍`, 'confirmation');
      }

      setSelectedLocationBadge(null);
    },
    [
      tripInputs.destinations,
      documentStore,
      branches,
      selectedBranchId,
      onBranchesChange,
      onSelectedBranchIdChange,
      onToast,
    ]
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
