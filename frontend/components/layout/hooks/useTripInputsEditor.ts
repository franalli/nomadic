'use client';

import { useCallback, useEffect, useState } from 'react';

import {
  toTripInputsDraft,
  type TripInputsDraft,
} from '@/components/layout/TripDetailsForm';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch, DocumentTripInputs } from '@/types/document';

export interface ChatPanelActions {
  addAssistantMessage: (message: string) => void;
}

export interface TripInputsEditorOptions {
  tripInputs: DocumentTripInputs;
  storeTripInputs: DocumentTripInputs | null | undefined;
  branches: DocumentBranch[];
  selectedBranchId: string | null;
  chatPanelActions: ChatPanelActions | null;
  onBranchesChange: (branches: DocumentBranch[]) => void;
  onSelectedBranchIdChange: (branchId: string | null) => void;
  onToast: (message: string) => void;
}

export interface TripInputsEditorState {
  tripInputsDraft: TripInputsDraft;
  editingField: keyof TripInputsDraft | null;
  selectedLocationBadge: 'origin' | number | null;
  vibeInput: string;
  vibeInputExpanded: boolean;
  destinationInput: string;
  destinationInputExpanded: boolean;
  originInput: string;
  originInputExpanded: boolean;
}

export interface TripInputsEditorActions {
  setTripInputsDraft: React.Dispatch<React.SetStateAction<TripInputsDraft>>;
  setEditingField: React.Dispatch<React.SetStateAction<keyof TripInputsDraft | null>>;
  setSelectedLocationBadge: React.Dispatch<React.SetStateAction<'origin' | number | null>>;
  setVibeInput: React.Dispatch<React.SetStateAction<string>>;
  setVibeInputExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  setDestinationInput: React.Dispatch<React.SetStateAction<string>>;
  setDestinationInputExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  setOriginInput: React.Dispatch<React.SetStateAction<string>>;
  setOriginInputExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  handleStartEditingField: (field: keyof TripInputsDraft) => void;
  handleFieldChange: (field: keyof TripInputsDraft, value: string) => void;
  handleCommitField: (field?: keyof TripInputsDraft, value?: string) => Promise<void>;
  handleSetOrigin: (origin: string) => Promise<void>;
  handleRemoveOrigin: () => Promise<void>;
  handleRemoveTravelerCount: () => Promise<void>;
  handleRemoveBudget: () => Promise<void>;
  handleToggleMultiCity: () => Promise<void>;
  handleAddDestination: (destination: string) => Promise<void>;
  handleRemoveDestination: (index: number) => Promise<void>;
  handleAddVibe: (vibe: string) => Promise<void>;
  handleRemoveVibe: (index: number) => Promise<void>;
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
    chatPanelActions,
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
  const [vibeInput, setVibeInput] = useState('');
  const [vibeInputExpanded, setVibeInputExpanded] = useState(false);
  const [destinationInput, setDestinationInput] = useState('');
  const [destinationInputExpanded, setDestinationInputExpanded] = useState(false);
  const [originInput, setOriginInput] = useState('');
  const [originInputExpanded, setOriginInputExpanded] = useState(false);

  // Sync tripInputsDraft when store trip_inputs changes
  // Always sync destinations and vibes (they're modified by bot, not inline editing)
  // Only skip other fields if user is actively editing them
  useEffect(() => {
    if (!storeTripInputs) return;

    setTripInputsDraft((prev) => {
      // Always update destinations and vibes from store (source of truth)
      // This ensures bot-initiated changes are reflected in UI
      const newDraft: TripInputsDraft = {
        ...prev,
        destinations: storeTripInputs.destinations ?? [],
        vibes: storeTripInputs.vibes ?? [],
      };

      // Only update other fields if not actively editing
      if (editingField === null) {
        newDraft.origin = storeTripInputs.origin ?? null;
        newDraft.start_date = storeTripInputs.start_date ?? null;
        newDraft.end_date = storeTripInputs.end_date ?? null;
        newDraft.traveler_count = storeTripInputs.traveler_count != null
          ? String(storeTripInputs.traveler_count)
          : null;
        newDraft.budget = storeTripInputs.budget != null
          ? String(storeTripInputs.budget)
          : null;
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
      if (field === 'traveler_count') {
        const count = parseInt(trimmedValue, 10);
        if (Number.isNaN(count) || count <= 0) {
          setTripInputsDraft((prev) => ({
            ...toTripInputsDraft(tripInputs),
            ...prev,
            traveler_count: prevValue != null ? String(prevValue) : '',
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
      } else if (field === 'traveler_count') {
        updates.traveler_count = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue, 10);
      } else if (field === 'budget') {
        updates.budget = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
      }

      const success = await documentStore.commitTripInputs(updates);

      if (!success) {
        onToast(`Failed to update ${field.replace('_', ' ')}. Please try again.`);
        return;
      }

      // Add assistant message to acknowledge the change
      let message: string | null = null;

      if (field === 'origin') {
        message = `Got it! Departing from ${trimmedValue}. ✈️`;
      } else if (field === 'traveler_count') {
        const count = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue, 10);
        if (!Number.isNaN(count)) {
          message = count === 1
            ? 'Noted! Planning for a solo adventure. 🎒'
            : `Noted! Planning for ${count} travelers. 👥`;
        }
      } else if (field === 'budget') {
        const budget = typeof parsedValue === 'number' ? parsedValue : parseInt(trimmedValue.replace(/[^\d]/g, ''), 10);
        if (!Number.isNaN(budget) && budget > 0) {
          message = `Got it! Budget set to $${budget.toLocaleString()}. 💰`;
        }
      }

      if (message) {
        chatPanelActions?.addAssistantMessage(message);
      }
    },
    [tripInputs, documentStore, onToast, chatPanelActions]
  );

  const handleSetOrigin = useCallback(
    async (origin: string) => {
      const trimmedOrigin = origin.trim();
      if (!trimmedOrigin) return;

      // Optimistically update via documentStore.commitTripInputs
      const success = await documentStore.commitTripInputs({ origin: trimmedOrigin });

      if (!success) {
        onToast('Failed to set origin. Please try again.');
        return;
      }

      setOriginInput('');

      // Add assistant message to acknowledge
      chatPanelActions?.addAssistantMessage(`Set "${trimmedOrigin}" as your departure city! ✈️`);
    },
    [documentStore, onToast, chatPanelActions]
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
      onToast('Failed to remove origin. Please try again.');
      return;
    }

    // Add assistant message to acknowledge the removal
    chatPanelActions?.addAssistantMessage(`Removed "${removedOrigin}" as your departure city. 📍`);

    setSelectedLocationBadge(null);
  }, [tripInputs.origin, documentStore, onToast, chatPanelActions]);

  const handleRemoveTravelerCount = useCallback(async () => {
    if (tripInputs.traveler_count == null) return;

    const success = await documentStore.commitTripInputs({ traveler_count: null });

    if (!success) {
      onToast('Failed to clear traveler count. Please try again.');
      return;
    }

    chatPanelActions?.addAssistantMessage('Cleared the traveler count. 👥');
  }, [tripInputs.traveler_count, documentStore, onToast, chatPanelActions]);

  const handleRemoveBudget = useCallback(async () => {
    if (tripInputs.budget == null) return;

    const success = await documentStore.commitTripInputs({ budget: null });

    if (!success) {
      onToast('Failed to clear budget. Please try again.');
      return;
    }

    chatPanelActions?.addAssistantMessage('Cleared the budget. 💰');
  }, [tripInputs.budget, documentStore, onToast, chatPanelActions]);

  const handleToggleMultiCity = useCallback(async () => {
    const currentIntent = tripInputs.multi_city_intent;
    // Toggle: null/separate -> multi_city, multi_city -> separate
    const newIntent = currentIntent === 'multi_city' ? 'separate' : 'multi_city';

    const success = await documentStore.commitTripInputs({ multi_city_intent: newIntent });

    if (!success) {
      onToast('Failed to update trip style. Please try again.');
      return;
    }

    const message = newIntent === 'multi_city'
      ? 'Switched to one combined itinerary visiting all destinations! 🗺️'
      : 'Switched to separate trip options for each destination! 📍';
    chatPanelActions?.addAssistantMessage(message);
  }, [tripInputs.multi_city_intent, documentStore, onToast, chatPanelActions]);

  const handleAddDestination = useCallback(
    async (destination: string) => {
      const trimmedDestination = destination.trim();
      if (!trimmedDestination) return;

      const currentDestinations = tripInputs.destinations ?? [];
      // Don't add duplicates (case-insensitive)
      if (currentDestinations.some((d) => d.toLowerCase() === trimmedDestination.toLowerCase())) {
        setDestinationInput('');
        return;
      }

      const newDestinations = [...currentDestinations, trimmedDestination];

      // Optimistically update via documentStore.commitTripInputs
      const success = await documentStore.commitTripInputs({ destinations: newDestinations });

      if (!success) {
        onToast('Failed to add destination. Please try again.');
        return;
      }

      setDestinationInput('');

      // Add assistant message to acknowledge the addition
      chatPanelActions?.addAssistantMessage(`Added "${trimmedDestination}" to your destinations! 📍`);
    },
    [tripInputs.destinations, documentStore, onToast, chatPanelActions]
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
              `Removed ${removedDestination} — your trip options were reset. Click "Generate Plan" to create new options.`
            );
          } else {
            // Some branches remain - update selection if needed
            if (selectedBranchId && !prunedBranches.find((b) => b.id === selectedBranchId)) {
              const newSelectedId = prunedBranches.find((b) => b.is_primary)?.id ?? prunedBranches[0]?.id ?? null;
              onSelectedBranchIdChange(newSelectedId);
            }
            onToast(
              `Removed ${removedDestination} — ${removedCount} trip option${removedCount > 1 ? 's were' : ' was'} updated.`
            );
          }
        }
      }

      // Optimistically update via documentStore.commitTripInputs
      // This updates the UI immediately and syncs to backend in background
      const success = await documentStore.commitTripInputs({ destinations: newDestinations });

      if (!success) {
        // Show error toast on failure (store already rolled back)
        onToast('Failed to remove destination. Please try again.');
        return;
      }

      // Add assistant message to acknowledge the removal
      if (removedDestination) {
        chatPanelActions?.addAssistantMessage(`Removed "${removedDestination}" from your destinations. 📍`);
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
      chatPanelActions,
    ]
  );

  const handleAddVibe = useCallback(
    async (vibe: string) => {
      const trimmedVibe = vibe.trim().toLowerCase();
      if (!trimmedVibe) return;

      const currentVibes = tripInputs.vibes ?? [];
      // Don't add duplicates (case-insensitive)
      if (currentVibes.some((v) => v.toLowerCase() === trimmedVibe)) {
        setVibeInput('');
        return;
      }

      const newVibes = [...currentVibes, trimmedVibe];

      // Optimistically update via documentStore.commitTripInputs (like handleRemoveVibe does)
      const success = await documentStore.commitTripInputs({ vibes: newVibes });

      if (!success) {
        onToast('Failed to add vibe. Please try again.');
        return;
      }

      setVibeInput('');

      // Add an assistant message to confirm the vibe was added
      chatPanelActions?.addAssistantMessage(`Added "${trimmedVibe}" to your trip vibes! ✨`);
    },
    [tripInputs.vibes, documentStore, onToast, chatPanelActions]
  );

  const handleRemoveVibe = useCallback(
    async (index: number) => {
      const currentVibes = tripInputs.vibes ?? [];
      if (index < 0 || index >= currentVibes.length) return;

      const removedVibe = currentVibes[index];
      const newVibes = currentVibes.filter((_, i) => i !== index);

      // Optimistically update via documentStore.commitTripInputs
      const success = await documentStore.commitTripInputs({ vibes: newVibes });

      if (!success) {
        onToast('Failed to remove vibe. Please try again.');
        return;
      }

      // Add an assistant message to confirm the vibe was removed
      if (removedVibe) {
        chatPanelActions?.addAssistantMessage(`Removed "${removedVibe}" from your trip vibes.`);
      }
    },
    [tripInputs.vibes, documentStore, onToast, chatPanelActions]
  );

  const resetDraft = useCallback(() => {
    setTripInputsDraft(toTripInputsDraft(DEFAULT_TRIP_INPUTS));
    setEditingField(null);
    setSelectedLocationBadge(null);
    setVibeInput('');
    setVibeInputExpanded(false);
    setDestinationInput('');
    setDestinationInputExpanded(false);
    setOriginInput('');
    setOriginInputExpanded(false);
  }, []);

  return {
    // State
    tripInputsDraft,
    editingField,
    selectedLocationBadge,
    vibeInput,
    vibeInputExpanded,
    destinationInput,
    destinationInputExpanded,
    originInput,
    originInputExpanded,
    // State setters
    setTripInputsDraft,
    setEditingField,
    setSelectedLocationBadge,
    setVibeInput,
    setVibeInputExpanded,
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
    handleRemoveTravelerCount,
    handleRemoveBudget,
    handleToggleMultiCity,
    handleAddDestination,
    handleRemoveDestination,
    handleAddVibe,
    handleRemoveVibe,
    resetDraft,
  };
}
