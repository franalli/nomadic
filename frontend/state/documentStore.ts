/**
 * Centralized state store for PlanDocument using Zustand.
 * This is the single source of truth for branches and tiles in the frontend.
 */

import { create } from 'zustand';

import { apiFetch } from '@/lib/api';
import type {
  BranchSelections,
  DocumentBranch,
  DocumentTripInputs,
  DocumentTripInputsPatch,
  PlanDocumentData,
  PlanDocumentPatch,
  PlanDocumentResponse,
  UpdatedBy,
} from '@/types/document';
import type { Tile } from '@/types/tile';

/**
 * Default trip inputs when no document exists yet.
 */
const DEFAULT_TRIP_INPUTS: DocumentTripInputs = {
  destinations: [],
  origin: null,
  start_date: null,
  end_date: null,
  traveler_count: null,
  budget: null,
  missing_fields: [
    'destinations',
    'origin',
    'start_date',
    'end_date',
    'traveler_count',
    'budget',
  ],
  vibes: [],
};

type DocumentState = {
  // Document data
  version: number;
  updatedBy: UpdatedBy | null;
  updatedAt: string | null;
  document: PlanDocumentData | null;

  // Version tracking for auto-refresh loop prevention
  // This tracks the version we last received from backend, to distinguish
  // between user-initiated changes and backend-initiated updates
  lastConfirmedVersion: number;

  // UI state
  selectedBranchId: string | null;
  isLoading: boolean;
  error: string | null;

  // Trip input selectors (computed from document)
  getTripInputs: () => DocumentTripInputs;
  getMissingFields: () => string[];
  isReadyToGenerate: () => boolean;
  hasAllRequiredFields: () => boolean;

  // Trip input actions
  commitTripInputs: (updates: DocumentTripInputsPatch) => Promise<boolean>;

  // Actions
  fetchDocument: () => Promise<void>;
  patchDocument: (patch: PlanDocumentPatch) => Promise<void>;
  fetchTilesForBranch: (branchId: string) => Promise<void>;

  // Selection actions
  selectBranch: (branchId: string) => void;
  selectTile: (
    branchId: string,
    tileId: string,
    tileType: 'stay' | 'flight' | 'activity'
  ) => Promise<void>;
  deselectTile: (
    branchId: string,
    tileType: 'stay' | 'flight' | 'activity',
    tileId?: string
  ) => Promise<void>;

  // Merge from plan response (when /v1/plan returns new branches) - legacy
  mergeFromPlanResponse: (
    branches: DocumentBranch[],
    tiles: Record<string, Tile>,
    tripContextId: number
  ) => void;

  // Set document from plan response (when /v1/plan returns new document)
  setFromPlanResponse: (response: PlanDocumentResponse) => void;

  // Reset
  reset: () => void;
};

const initialState = {
  version: 0,
  updatedBy: null as UpdatedBy | null,
  updatedAt: null as string | null,
  document: null as PlanDocumentData | null,
  lastConfirmedVersion: 0,
  selectedBranchId: null as string | null,
  isLoading: false,
  error: null as string | null,
};

export const useDocumentStore = create<DocumentState>((set, get) => ({
  ...initialState,

  // Trip input selectors
  getTripInputs: () => {
    const { document } = get();
    return document?.trip_inputs ?? DEFAULT_TRIP_INPUTS;
  },

  getMissingFields: () => {
    const { document } = get();
    return document?.trip_inputs?.missing_fields ?? DEFAULT_TRIP_INPUTS.missing_fields;
  },

  isReadyToGenerate: () => {
    const { document } = get();
    return document?.ready_to_generate ?? false;
  },

  hasAllRequiredFields: () => {
    const { document } = get();
    const missingFields = document?.trip_inputs?.missing_fields ?? DEFAULT_TRIP_INPUTS.missing_fields;
    return missingFields.length === 0;
  },

  // Trip input actions
  commitTripInputs: async (updates: DocumentTripInputsPatch): Promise<boolean> => {
    const { document, version } = get();

    // If no document exists yet, we can't commit trip inputs
    // The document is created by the backend when the first chat message is sent
    if (!document) {
      console.warn('commitTripInputs called but no document exists yet');
      return false;
    }

    // Store previous state for rollback
    const previousTripInputs = document.trip_inputs;

    // Compute updated destinations
    const newDestinations = updates.destinations ?? document.trip_inputs.destinations;

    // Compute updated missing_fields based on destinations change
    let updatedMissingFields = [...(document.trip_inputs.missing_fields ?? [])];
    if (updates.destinations !== undefined) {
      if (updates.destinations.length === 0) {
        // Add 'destinations' to missing_fields if not present
        if (!updatedMissingFields.includes('destinations')) {
          updatedMissingFields.push('destinations');
        }
      } else {
        // Remove 'destinations' from missing_fields if present
        updatedMissingFields = updatedMissingFields.filter(f => f !== 'destinations');
      }
    }

    const updatedTripInputs: DocumentTripInputs = {
      ...document.trip_inputs,
      ...updates,
      destinations: newDestinations,
      missing_fields: updatedMissingFields,
    };

    // Optimistically update the store
    set({
      document: {
        ...document,
        trip_inputs: updatedTripInputs,
      },
    });

    // Helper to attempt PATCH with given version
    const attemptPatch = async (patchVersion: number): Promise<PlanDocumentResponse> => {
      const patch: PlanDocumentPatch = {
        version: patchVersion,
        trip_inputs: updates,
      };

      const res = await apiFetch('/v1/document', {
        method: 'PATCH',
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        throw new Error(`${res.status}`);
      }
      return res.json();
    };

    // Send to backend
    try {
      const response = await attemptPatch(version);

      // Update with backend response (authoritative)
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
        lastConfirmedVersion: response.version,
        error: null,
      });

      return true;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '';

      // Handle 409 Conflict (version mismatch) - refetch and retry once
      if (errorMessage.includes('409')) {
        try {
          // Fetch fresh document state
          const freshRes = await apiFetch('/v1/document');
          if (!freshRes.ok) {
            throw new Error('Failed to refresh document');
          }
          const freshResponse: PlanDocumentResponse = await freshRes.json();

          // Retry with fresh version
          const retryResponse = await attemptPatch(freshResponse.version);

          // Update with retry response (authoritative)
          set({
            version: retryResponse.version,
            updatedBy: retryResponse.updated_by,
            updatedAt: retryResponse.updated_at,
            document: retryResponse.document,
            lastConfirmedVersion: retryResponse.version,
            error: null,
          });

          return true;
        } catch (retryErr) {
          // Retry failed - rollback
          set({
            document: {
              ...document,
              trip_inputs: previousTripInputs,
            },
            error: retryErr instanceof Error ? retryErr.message : 'Failed to update trip inputs',
          });
          return false;
        }
      }

      // Non-409 error - rollback
      set({
        document: {
          ...document,
          trip_inputs: previousTripInputs,
        },
        error: errorMessage || 'Failed to update trip inputs',
      });
      return false;
    }
  },

  fetchDocument: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch('/v1/document');
      if (!res.ok) {
        if (res.status === 204 || res.status === 404) {
          // 204: No document yet (expected for new sessions)
          // 404: Legacy handling
          set({ isLoading: false, document: null });
          return;
        }
        throw new Error(`${res.status}`);
      }
      const response: PlanDocumentResponse = await res.json();
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
        lastConfirmedVersion: response.version,
        isLoading: false,
        // Auto-select primary branch if none selected
        selectedBranchId:
          get().selectedBranchId ||
          response.document.branches.find((b) => b.is_primary)?.id ||
          response.document.branches[0]?.id ||
          null,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch document';
      set({ isLoading: false, error: message });
    }
  },

  patchDocument: async (patch: PlanDocumentPatch) => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch('/v1/document', {
        method: 'PATCH',
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        throw new Error(`${res.status}`);
      }
      const response: PlanDocumentResponse = await res.json();
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
        lastConfirmedVersion: response.version,
        isLoading: false,
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to update document',
      });
    }
  },

  fetchTilesForBranch: async (branchId: string) => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch(
        `/v1/document/tiles/${encodeURIComponent(branchId)}`,
        { method: 'POST' }
      );
      if (!res.ok) {
        throw new Error(`${res.status}`);
      }
      const response: PlanDocumentResponse = await res.json();
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
        lastConfirmedVersion: response.version,
        isLoading: false,
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to fetch tiles',
      });
    }
  },

  selectBranch: (branchId: string) => {
    set({ selectedBranchId: branchId });
  },

  selectTile: async (
    branchId: string,
    tileId: string,
    tileType: 'stay' | 'flight' | 'activity'
  ) => {
    const { document, version } = get();
    if (!document) return;

    const branch = document.branches.find((b) => b.id === branchId);
    if (!branch) return;

    // Build updated selections
    const updatedSelections: BranchSelections = { ...branch.selections };
    if (tileType === 'stay') {
      updatedSelections.stay = tileId;
    } else if (tileType === 'flight') {
      updatedSelections.flight = tileId;
    } else if (tileType === 'activity') {
      if (!updatedSelections.activities.includes(tileId)) {
        updatedSelections.activities = [...updatedSelections.activities, tileId];
      }
    }

    const patch: PlanDocumentPatch = {
      version,
      selections: { [branchId]: updatedSelections },
    };

    await get().patchDocument(patch);
  },

  deselectTile: async (
    branchId: string,
    tileType: 'stay' | 'flight' | 'activity',
    tileId?: string
  ) => {
    const { document, version } = get();
    if (!document) return;

    const branch = document.branches.find((b) => b.id === branchId);
    if (!branch) return;

    // Build updated selections
    const updatedSelections: BranchSelections = { ...branch.selections };
    if (tileType === 'stay') {
      updatedSelections.stay = null;
    } else if (tileType === 'flight') {
      updatedSelections.flight = null;
    } else if (tileType === 'activity' && tileId) {
      updatedSelections.activities = updatedSelections.activities.filter(
        (id) => id !== tileId
      );
    }

    const patch: PlanDocumentPatch = {
      version,
      selections: { [branchId]: updatedSelections },
    };

    await get().patchDocument(patch);
  },

  mergeFromPlanResponse: (
    branches: DocumentBranch[],
    tiles: Record<string, Tile>,
    tripContextId: number
  ) => {
    const { document } = get();

    // If no document yet, create one
    if (!document) {
      set({
        document: {
          trip_context_id: tripContextId,
          trip_inputs: { ...DEFAULT_TRIP_INPUTS },
          branches,
          tiles,
        },
        version: 1,
        updatedBy: 'planner',
        updatedAt: new Date().toISOString(),
        selectedBranchId:
          branches.find((b) => b.is_primary)?.id || branches[0]?.id || null,
      });
      return;
    }

    // Merge branches (CRDT: additions win)
    const branchMap = new Map(document.branches.map((b) => [b.id, b]));
    for (const branch of branches) {
      branchMap.set(branch.id, branch);
    }

    // Merge tiles
    const mergedTiles = { ...document.tiles, ...tiles };

    set({
      document: {
        ...document,
        trip_context_id: tripContextId,
        branches: Array.from(branchMap.values()),
        tiles: mergedTiles,
      },
      version: get().version + 1,
      updatedBy: 'planner',
      updatedAt: new Date().toISOString(),
      selectedBranchId:
        get().selectedBranchId ||
        branches.find((b) => b.is_primary)?.id ||
        branches[0]?.id ||
        null,
    });
  },

  setFromPlanResponse: (response: PlanDocumentResponse) => {
    const primaryBranch = response.document.branches.find((b) => b.is_primary);
    set({
      version: response.version,
      updatedBy: response.updated_by,
      updatedAt: response.updated_at,
      document: response.document,
      lastConfirmedVersion: response.version,
      selectedBranchId:
        get().selectedBranchId ||
        primaryBranch?.id ||
        response.document.branches[0]?.id ||
        null,
    });
  },

  reset: () => {
    set(initialState);
  },
}));
