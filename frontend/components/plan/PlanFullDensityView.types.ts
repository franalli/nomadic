'use client';

import type { RefObject } from 'react';

import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import type { GenerationState } from './planStateHelpers';
import type { TimelineVariant } from './TimelineThread';

export interface PlanFullDensityViewProps {
  state: PlanViewState;
  viewModel: PlanViewModel;
  fullModeSections: PlanViewModel['strategy_sections'];
  fullModePOIs: MapPOI[];
  effectiveTiles: Record<string, Tile>;
  effectiveTripInputs: DocumentTripInputs | undefined;
  destinationCard?: DestinationCard;
  generation?: GenerationState | null;
  savedTileIds: Set<string>;
  hasSectionData: boolean;
  hasItineraryContent: boolean;
  isExpandingItinerary: boolean;
  isStreaming: boolean;
  isAnyRegenerating: boolean;
  isRegenUpdating: boolean;
  isDesktop: boolean;
  preferenceCount: number;
  effectiveMode: string;
  timelineVariant: TimelineVariant;
  timelineSectionRef: RefObject<HTMLDivElement | null>;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  handleSaveTile: (tile: Tile) => Promise<void>;
  handleOpenBookingDrawer: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
  onOpenSheet?: (sheet: SheetType) => void;
}
