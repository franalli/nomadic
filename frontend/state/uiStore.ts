/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * UI State Store - Separated from Document Store
 *
 * This store manages UI-specific state that is NOT document data:
 * - Branch selection (which branch is currently viewed)
 * - Comparison mode (UI toggle for comparing branches)
 * - Loading/error states for UI operations
 *
 * Benefits of separation:
 * - UI state can be reset without losing document data
 * - Document store can focus on data persistence
 * - Easier session serialization (can serialize document without UI state)
 * - Clearer responsibility boundaries
 *
 * Tier 9: Added localStorage persistence to preserve UI state across refreshes.
 * Uses Zustand's persist middleware with session-scoped storage key.
 */

import { create } from 'zustand';
import { createJSONStorage,persist } from 'zustand/middleware';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

type UIState = {
  // Branch selection
  selectedBranchId: string | null;

  // Comparison mode
  isComparisonMode: boolean;
  comparisonBranchIds: [string, string] | null;

  // Hover sync (card ↔ map, ephemeral — not persisted)
  hoveredActivityId: string | null;
  setHoveredActivityId: (id: string | null) => void;

  // Actions
  setSelectedBranchId: (branchId: string | null) => void;
  selectBranchIfNone: (branchId: string) => void;

  // Comparison mode actions
  setComparisonMode: (enabled: boolean) => void;
  toggleBranchForComparison: (branchId: string) => void;
  exitComparisonMode: () => void;

  // Reset
  resetUI: () => void;
};

// ─────────────────────────────────────────────────────────────────────────────
// Initial State
// ─────────────────────────────────────────────────────────────────────────────

const initialUIState = {
  selectedBranchId: null as string | null,
  isComparisonMode: false,
  comparisonBranchIds: null as [string, string] | null,
  hoveredActivityId: null as string | null,
};

// ─────────────────────────────────────────────────────────────────────────────
// Storage Key
// ─────────────────────────────────────────────────────────────────────────────

const UI_STORAGE_KEY = 'nomadic-ui-state';

// ─────────────────────────────────────────────────────────────────────────────
// Store
// ─────────────────────────────────────────────────────────────────────────────

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      ...initialUIState,

      setHoveredActivityId: (id: string | null) => set({ hoveredActivityId: id }),

      setSelectedBranchId: (branchId: string | null) => {
        set({ selectedBranchId: branchId });
      },

      selectBranchIfNone: (branchId: string) => {
        const { selectedBranchId } = get();
        if (!selectedBranchId) {
          set({ selectedBranchId: branchId });
        }
      },

      setComparisonMode: (enabled: boolean) => {
        if (!enabled) {
          set({ isComparisonMode: false, comparisonBranchIds: null });
        } else {
          // When entering comparison mode, reset comparison state
          set({
            isComparisonMode: true,
            // Don't set comparisonBranchIds yet - user needs to select second branch
            comparisonBranchIds: null,
          });
        }
      },

      toggleBranchForComparison: (branchId: string) => {
        const { isComparisonMode, comparisonBranchIds, selectedBranchId } = get();

        if (!isComparisonMode) {
          // Enter comparison mode with this branch as first
          set({
            isComparisonMode: true,
            comparisonBranchIds: null,
            selectedBranchId: branchId,
          });
          return;
        }

        if (!comparisonBranchIds) {
          // First branch selection in comparison mode
          // Use selectedBranchId as first, clicked branch as second
          const firstBranch = selectedBranchId || branchId;
          if (firstBranch !== branchId) {
            set({ comparisonBranchIds: [firstBranch, branchId] });
          }
          return;
        }

        const [first, second] = comparisonBranchIds;

        if (branchId === first || branchId === second) {
          // Clicking an already-selected branch - deselect and exit comparison
          set({
            isComparisonMode: false,
            comparisonBranchIds: null,
            selectedBranchId: branchId === first ? second : first,
          });
        } else {
          // Replace second branch with new selection
          set({ comparisonBranchIds: [first, branchId] });
        }
      },

      exitComparisonMode: () => {
        const { comparisonBranchIds, selectedBranchId } = get();
        set({
          isComparisonMode: false,
          comparisonBranchIds: null,
          // Keep first comparison branch as selected
          selectedBranchId: comparisonBranchIds?.[0] || selectedBranchId,
        });
      },

      resetUI: () => {
        set({ ...initialUIState });
      },
    }),
    {
      name: UI_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      // Only persist these specific fields - exclude actions
      partialize: (state) => ({
        selectedBranchId: state.selectedBranchId,
        isComparisonMode: state.isComparisonMode,
        comparisonBranchIds: state.comparisonBranchIds,
      }),
      // Version for future migrations
      version: 1,
    }
  )
);

/**
 * Clear persisted UI state from localStorage.
 * Call this on logout or when switching sessions.
 */
export function clearPersistedUIState(): void {
  localStorage.removeItem(UI_STORAGE_KEY);
  useUIStore.getState().resetUI();
}
