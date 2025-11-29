/**
 * Centralized state store for PlanDocument using Zustand.
 * This is the single source of truth for branches and tiles in the frontend.
 */

import { create } from 'zustand';

import { apiFetch } from '@/lib/api';
import type {
  BranchSelections,
  DocumentBranch,
  PlanDocumentData,
  PlanDocumentPatch,
  PlanDocumentResponse,
  UpdatedBy,
} from '@/types/document';
import type { Tile } from '@/types/tile';

type DocumentState = {
  // Document data
  version: number;
  updatedBy: UpdatedBy | null;
  updatedAt: string | null;
  document: PlanDocumentData | null;

  // UI state
  selectedBranchId: string | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  fetchDocument: (sessionId: string) => Promise<void>;
  patchDocument: (sessionId: string, patch: PlanDocumentPatch) => Promise<void>;
  fetchTilesForBranch: (sessionId: string, branchId: string) => Promise<void>;

  // Selection actions
  selectBranch: (branchId: string) => void;
  selectTile: (
    sessionId: string,
    branchId: string,
    tileId: string,
    tileType: 'stay' | 'flight' | 'activity'
  ) => Promise<void>;
  deselectTile: (
    sessionId: string,
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
  selectedBranchId: null as string | null,
  isLoading: false,
  error: null as string | null,
};

export const useDocumentStore = create<DocumentState>((set, get) => ({
  ...initialState,

  fetchDocument: async (sessionId: string) => {
    set({ isLoading: true, error: null });
    try {
      const response: PlanDocumentResponse = await apiFetch(
        `/v1/document?session_id=${encodeURIComponent(sessionId)}`
      );
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
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
      // 404 is expected for new sessions
      if (message.includes('404')) {
        set({ isLoading: false, document: null });
      } else {
        set({ isLoading: false, error: message });
      }
    }
  },

  patchDocument: async (sessionId: string, patch: PlanDocumentPatch) => {
    set({ isLoading: true, error: null });
    try {
      const response: PlanDocumentResponse = await apiFetch(
        `/v1/document?session_id=${encodeURIComponent(sessionId)}`,
        {
          method: 'PATCH',
          body: JSON.stringify(patch),
        }
      );
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
        isLoading: false,
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to update document',
      });
    }
  },

  fetchTilesForBranch: async (sessionId: string, branchId: string) => {
    set({ isLoading: true, error: null });
    try {
      const response: PlanDocumentResponse = await apiFetch(
        `/v1/document/tiles/${encodeURIComponent(branchId)}?session_id=${encodeURIComponent(sessionId)}`,
        { method: 'POST' }
      );
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
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
    sessionId: string,
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

    await get().patchDocument(sessionId, patch);
  },

  deselectTile: async (
    sessionId: string,
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

    await get().patchDocument(sessionId, patch);
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
          trip_inputs: { missing_fields: [] },
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
