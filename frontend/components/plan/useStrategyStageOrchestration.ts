'use client';

/**
 * useStrategyStageOrchestration
 *
 * Centralises all heavy computation, state, and effects for StrategyStageRenderer.
 * Extracted to keep the renderer under ~300 lines as per CLAUDE.md.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useStoreWithEqualityFn } from 'zustand/traditional';

import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { useScrollCollapse } from '@/hooks/useScrollCollapse';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import {
  extractPOIsFromDayCards,
  hasSpecialistContent,
} from '@/lib/ghost-timeline-adapter';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import { normalizePlanViewState, type PlanViewModel, type PlanViewState, type ViewMode } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { type ProgressStage } from './ItineraryProgressIndicator';
import { type GenerationState, getNextAction, isGenerating, isMultiSpecialistTrip } from './planStateHelpers';
import { getTopicLabel } from './stages/StrategyHeroUtils';
import { useBookingDrawerState } from './useBookingDrawerState';

export type DataDensity = 'empty' | 'ghost' | 'bridge' | 'full';

export function computeDataDensity(
  state: PlanViewState,
  strategySections: PlanViewModel['strategy_sections'],
  tiles: Record<string, Tile> | undefined,
  hasDates: boolean = false,
): DataDensity {
  const hasSpecialist = hasSpecialistContent(strategySections);
  const hasTiles = tiles && Object.keys(tiles).length > 0;
  const normalizedState = normalizePlanViewState(state);
  if (normalizedState === 'P0_MINIMAL' && hasSpecialist && hasDates) return 'ghost';
  if (normalizedState === 'P0_MINIMAL' && hasSpecialist) return 'bridge';
  if (normalizedState === 'P0_MINIMAL') return 'empty';
  if (normalizedState === 'P1_ENRICHED' && hasSpecialist && !hasTiles) return 'bridge';
  return 'full';
}

interface UseOrchestrationInput {
  state: PlanViewState;
  viewModel: PlanViewModel;
  tiles: Record<string, Tile>;
  generation?: GenerationState | null;
  canGeneratePlan: boolean;
  hasDates: boolean;
  isExpandingItinerary: boolean;
  isCommitting: boolean;
  isRegenerating: boolean;
  onSaveTile?: (tile: Tile) => void;
  tripInputs?: DocumentTripInputs;
  mode?: ViewMode;
  destinationTitle?: string;
}

export function useStrategyStageOrchestration(input: UseOrchestrationInput) {
  const {
    state, viewModel, tiles, generation, canGeneratePlan, hasDates,
    isExpandingItinerary, isCommitting, isRegenerating, onSaveTile,
    tripInputs, mode: explicitMode, destinationTitle,
  } = input;

  const effectiveTripInputs = useTripInputsWithFallback(tripInputs);
  const { toast } = useToast();
  const storeTiles = useDocumentStore((s) => s.document?.tiles);
  const storeDayCardsRaw = useDocumentStore((s) => s.document?.day_cards);
  const toggleTilePreference = useDocumentStore((s) => s.toggleTilePreference);
  const isRegenUpdating = useDocumentStore((s) => s.isRegenerating);
  const preferredTileIds = useStoreWithEqualityFn(
    useDocumentStore,
    (s) => s.preferredTileIds,
    (a, b) => a.size === b.size && [...a].every((id) => b.has(id))
  );

  const dayCardsFingerprint = useMemo(() => {
    const cards = storeDayCardsRaw;
    if (!cards || cards.length === 0) return null;
    const blockFingerprint = cards
      .flatMap((card, cardIdx) => (card.blocks ?? []).map((block) => (
        `${cardIdx}:${block.id ?? ''}:${block.summary ?? ''}:${block.period ?? ''}:` +
        `${block.activity_type ?? ''}:${block.scheduled_time ?? ''}:` +
        `${block.coordinates?.lat ?? ''}:${block.coordinates?.lng ?? ''}`
      )))
      .join('|');
    return `${cards.length}:${blockFingerprint}`;
  }, [storeDayCardsRaw]);
  const effectiveTiles = storeTiles ?? tiles;

  const stableDayCardsRef = useRef(storeDayCardsRaw);
  const prevFingerprintRef = useRef(dayCardsFingerprint);
  if (dayCardsFingerprint !== prevFingerprintRef.current) {
    prevFingerprintRef.current = dayCardsFingerprint;
    stableDayCardsRef.current = storeDayCardsRaw;
  }
  const effectiveDayCards = stableDayCardsRef.current ?? viewModel.day_cards;

  const isAnyRegenerating = isRegenerating || isRegenUpdating;
  const hasSectionData = (viewModel.strategy_sections?.length ?? 0) > 0;
  const isDesktop = useIsDesktop();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isCollapsed = useScrollCollapse(scrollContainerRef, { threshold: 60, hysteresis: 15 });
  const timelineSectionRef = useRef<HTMLDivElement>(null);
  const prevHasItineraryRef = useRef(false);
  const frozenScrollRef = useRef<number | null>(null);

  useEffect(() => { guardedEnforcePolicy(state, viewModel); }, [state, viewModel]);

  const hasItineraryContent: boolean = state === 'S3_ITINERARY_READY' || state === 'S3_EDITING' ||
    Boolean(viewModel.day_cards && viewModel.day_cards.length > 0);

  const [showConstraints, setShowConstraints] = useState(false);
  const [stableDensity, setStableDensity] = useState<DataDensity>('empty');

  useEffect(() => {
    if (isExpandingItinerary && !hasItineraryContent) frozenScrollRef.current = window.scrollY;
  }, [isExpandingItinerary, hasItineraryContent]);
  useLayoutEffect(() => {
    if (hasItineraryContent && !prevHasItineraryRef.current && frozenScrollRef.current !== null) {
      window.scrollTo(0, frozenScrollRef.current);
      frozenScrollRef.current = null;
    }
  }, [hasItineraryContent]);
  useEffect(() => {
    if (hasItineraryContent && !prevHasItineraryRef.current) {
      prevHasItineraryRef.current = true;
      const timer = setTimeout(() => {
        timelineSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 100);
      return () => clearTimeout(timer);
    }
    prevHasItineraryRef.current = hasItineraryContent;
  }, [hasItineraryContent]);

  const prevInfeasibleRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const infeasibleSections = (viewModel.strategy_sections ?? []).filter(
      s => s.feasibility_status === 'infeasible' || s.feasibility_status === 'caveat'
    );
    const newInfeasible = infeasibleSections.filter(
      s => !prevInfeasibleRef.current.has(s.specialist_type ?? s.title)
    );
    if (newInfeasible.length > 0) {
      const destination = effectiveTripInputs?.destination ?? destinationTitle ?? 'this destination';
      newInfeasible.forEach(section => {
        const name = section.title || getTopicLabel(section.specialist_type ?? '') || 'Activity';
        const reason = section.feasibility_reason || 'Try a different destination.';
        toast(`${name} unavailable in ${destination}. ${reason}`, { type: 'warning', duration: 5000 });
      });
    }
    prevInfeasibleRef.current = new Set(infeasibleSections.map(s => s.specialist_type ?? s.title));
  }, [viewModel.strategy_sections, effectiveTripInputs?.destination, destinationTitle, toast]);

  const nextAction = getNextAction(state, generation, canGeneratePlan);
  const generating = isGenerating(generation);
  const isMultiSpecialist = isMultiSpecialistTrip(viewModel.executed_strategy_topics);
  const shouldShowAutoProgress = isMultiSpecialist && state === 'S2_STRATEGY_READY' && hasDates && generating;
  const hideNextStepBar = isMultiSpecialist && state === 'S2_STRATEGY_READY' && hasDates;
  const progressStage: ProgressStage = useMemo(() => {
    if (!generating) return 'success';
    const stage = generation?.stage;
    if (stage === 'itinerary') return 'building';
    if (stage === 'structure' || stage === 'strategy') return 'checking';
    return 'analyzing';
  }, [generating, generation?.stage]);
  const isStreaming = generating || isCommitting || isExpandingItinerary;
  const activeMode: ViewMode = useDocumentStore((s) => (s.activeView ?? 'planning') as ViewMode);
  const effectiveMode: ViewMode = explicitMode ?? activeMode;

  const displayLogic = useMemo(() => {
    const hasDatesLocal = hasDates;
    const hasTilesLocal = effectiveTiles && Object.keys(effectiveTiles).length > 0;
    const density = computeDataDensity(state, viewModel.strategy_sections, effectiveTiles, hasDates);
    const isShowingMirrorLoader = generating && hasDatesLocal && !hasTilesLocal;
    let tripDuration = effectiveTripInputs?.trip_duration ?? 3;
    if (effectiveTripInputs?.start_date && effectiveTripInputs?.end_date) {
      const start = new Date(effectiveTripInputs.start_date);
      const end = new Date(effectiveTripInputs.end_date);
      const diffDays = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;
      if (diffDays > 0) tripDuration = diffDays;
    }
    return { hasDates: hasDatesLocal, hasTiles: hasTilesLocal, density, isShowingMirrorLoader, tripDuration };
  }, [state, viewModel.strategy_sections, effectiveTiles, effectiveTripInputs, generating, hasDates]);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setStableDensity(displayLogic.density));
    return () => cancelAnimationFrame(raf);
  }, [displayLogic.density]);

  const specialistData = useMemo(() => {
    const fullModeSections = (viewModel.strategy_sections ?? []).filter(
      s => s.feasibility_status !== 'infeasible' && s.feasibility_status !== 'caveat'
    );
    const totalConstraints = fullModeSections.reduce((acc, s) => acc + (s.constraints_applied?.length ?? 0), 0);
    return { fullModeSections, totalConstraints,
      filteredViewModel: { ...viewModel, strategy_sections: fullModeSections } as PlanViewModel };
  }, [viewModel]);

  const destinationCoords = useMemo(() => {
    const hotelTile = Object.values(effectiveTiles).find(
      (t) => (t.type === 'hotel' || t.type === 'accommodation') && t.geo?.lat != null && t.geo?.lng != null,
    );
    if (hotelTile?.geo) return { lat: hotelTile.geo.lat, lng: hotelTile.geo.lng };
    return null;
  }, [effectiveTiles]);

  const fullModePOIs = useMemo(() => {
    if (!dayCardsFingerprint) return [];
    const destination = effectiveTripInputs?.destination ?? destinationTitle;
    return extractPOIsFromDayCards(effectiveDayCards, specialistData.fullModeSections, destination, dayCardsFingerprint, destinationCoords);
  }, [
    dayCardsFingerprint,
    effectiveTripInputs?.destination,
    destinationTitle,
    effectiveDayCards,
    specialistData,
    destinationCoords,
  ]);

  const bookingDrawer = useBookingDrawerState({
    generation, isCommitting, isExpandingItinerary, onSaveTile,
  });

  return {
    effectiveTripInputs, effectiveTiles, effectiveDayCards,
    preferredTileIds, toggleTilePreference,
    isRegenUpdating, isAnyRegenerating, hasSectionData,
    isDesktop, isCollapsed, scrollContainerRef, timelineSectionRef,
    hasItineraryContent, showConstraints, setShowConstraints,
    stableDensity, displayLogic, specialistData, fullModePOIs,
    nextAction, generating, isStreaming, effectiveMode,
    shouldShowAutoProgress, hideNextStepBar, progressStage,
    preferenceCount: preferredTileIds.size,
    ...bookingDrawer,
  };
}
