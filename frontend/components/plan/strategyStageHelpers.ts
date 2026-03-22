import type { DocumentTripInputs } from '@/types/document';
import type {
  DestinationCard,
  PlanViewModel,
  PlanViewState,
  ViewMode,
} from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { type GenerationState, isEditing, isItineraryReady, isStrategyReady } from './planStateHelpers';
import type { TimelineVariant } from './TimelineThread';
import type { DataDensity } from './useStrategyStageOrchestration';

export interface StrategyStageRendererProps {
  state: PlanViewState;
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
  tiles?: Record<string, Tile>;
  generation?: GenerationState | null;
  canGeneratePlan?: boolean;
  fallbackTitle?: string;
  hasDates?: boolean;
  isExpandingItinerary?: boolean;
  onBuildPlan?: () => void;
  onExpandToItinerary?: () => Promise<void>;
  onFinalizePlan?: () => void;
  isFinalizing?: boolean;
  onRefineAssumptions?: () => void;
  savedTileIds?: Set<string>;
  onSaveTile?: (tile: Tile) => void;
  tripInputs?: DocumentTripInputs;
  onOpenSheet?: (sheet: SheetType) => void;
  isCommitting?: boolean;
  hasEverHadPlan?: boolean;
  isRegenerating?: boolean;
  onSelectNights?: (nights: number) => void;
  mode?: ViewMode;
  onOpenActivitySettings?: () => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
}

export function shouldUsePlanMirrorLoader({
  isShowingMirrorLoader,
  density,
  isPlanGenerationActive,
  hasPartialItinerary = false,
  hasTiles = false,
}: {
  isShowingMirrorLoader: boolean;
  density: DataDensity;
  isPlanGenerationActive: boolean;
  hasPartialItinerary?: boolean;
  hasTiles?: boolean;
}): boolean {
  if (hasPartialItinerary) {
    return false;
  }

  // Keep skeleton visible during generation until day_cards arrive,
  // even if tiles are already present.
  if (hasTiles && isPlanGenerationActive) {
    return true;
  }

  if (isShowingMirrorLoader || density === 'ghost') {
    return true;
  }

  return isPlanGenerationActive && (density === 'empty' || density === 'bridge');
}

export function computeTimelineVariant(
  state: PlanViewState,
  hasPartialItinerary = false,
): TimelineVariant {
  if (isItineraryReady(state)) return 'real';
  if (hasPartialItinerary) return 'draft';
  if (isEditing(state) || isStrategyReady(state)) return 'draft';
  return 'ghost';
}

// Extracted animation constants to avoid re-creating objects on every render
export const FADE_INITIAL = { opacity: 0 } as const;
export const FADE_VISIBLE = { opacity: 1 } as const;
export const FADE_EXIT = { opacity: 0 } as const;
export const FADE_TRANSITION = { duration: 0.3, ease: [0.4, 0, 0.2, 1] } as const;
