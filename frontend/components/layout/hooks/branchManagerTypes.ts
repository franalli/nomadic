/**
 * Type definitions for useBranchManager hook.
 *
 * Extracted from useBranchManager.ts to reduce file size.
 * Canonical imports come from this file; useBranchManager.ts re-exports for
 * backward compatibility.
 */

import type {
  DocumentBranch,
  DocumentTripInputs,
  GraphPlanResponse,
  PlanStatus,
} from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { Tile, TileSelection } from '@/types/tile';

/**
 * Options for the useBranchManager hook.
 */
export interface BranchManagerOptions {
  /**
   * Ref to the chat panel container element.
   * Used to scroll and focus after starting a new session.
   */
  chatPanelContainerRef: React.RefObject<HTMLDivElement | null>;

  /**
   * Toast notification callback.
   * Used to show success/error messages to the user.
   */
  onToast: (message: string, type?: ToastType) => void;

  /**
   * Callback to increment the chat key.
   * Used to reset the chat panel when starting a new session.
   */
  onChatKeyIncrement: () => void;

  /**
   * Callback to reset the trip inputs draft.
   * Used when clearing context or starting a new session.
   */
  resetDraft: () => void;
}

/**
 * Payload received when a plan is generated.
 * Contains all branches, tiles, and metadata from the AI response.
 */
export interface PlanResultPayload {
  /** Trip context ID (null for anonymous sessions) */
  tripContextId: number | null;
  /** Generated trip branches (suggestions) */
  branches: DocumentBranch[];
  /** Map of all tiles referenced by branches */
  tiles: Record<string, Tile>;
  /** ID of the primary (recommended) branch */
  primaryBranchId: string | null;
  /** Updated trip inputs (if AI inferred any) */
  tripInputs?: DocumentTripInputs | null;
  /** Whether we have enough info to generate another plan */
  readyToGenerate?: boolean;
  /** Full API response for store updates */
  response?: GraphPlanResponse;
}

/**
 * State values from the branch manager.
 */
export interface BranchManagerState {
  branches: DocumentBranch[];
  selectedBranchId: string | null;
  tilesBranchId: string | null;
  branchSelections: Record<string, TileSelection>;
  isGenerating: boolean;
  isHydratingSnapshot: boolean;
  /** Plan regeneration status: ready, stale, or updating */
  planStatus: PlanStatus;
  /** Whether a regeneration is currently in-flight */
  isRegenerating: boolean;
}

/**
 * Computed values derived from state.
 */
export interface BranchManagerComputed {
  selectedBranch: DocumentBranch | null;
  activeBranchSelection: TileSelection;
  tiles: Tile[];
  readyToGenerate: boolean;
  hasBranchesReady: boolean;
}

/**
 * Actions available from the branch manager.
 */
export interface BranchManagerActions {
  setBranches: React.Dispatch<React.SetStateAction<DocumentBranch[]>>;
  setSelectedBranchId: React.Dispatch<React.SetStateAction<string | null>>;
  handleBranchSelect: (branchId: string) => Promise<void>;
  handleStartNewSession: () => Promise<void>;
  handlePlanResult: (result: PlanResultPayload) => void;
  handleTileSelection: (tile: Tile) => void;
  handleBookTrip: (branchId: string) => void;
  handleGeneratePlanStart: () => void;
}

/**
 * Complete return type combining state, computed values, and actions.
 */
export type UseBranchManagerReturn = BranchManagerState &
  BranchManagerComputed &
  BranchManagerActions;
