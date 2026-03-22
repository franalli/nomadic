'use client';

/**
 * useStrategyStageOrchestration
 *
 * Centralises all heavy computation, state, and effects for StrategyStageRenderer.
 * Extracted to keep the renderer under ~300 lines as per CLAUDE.md.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
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
import { useUIStore } from '@/state/uiStore';
import type { DocumentTripInputs } from '@/types/document';
import {
  type DayCard,
  normalizePlanViewState,
  type PlanViewModel,
  type PlanViewState,
  type ViewMode,
} from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { type ProgressStage } from './ItineraryProgressIndicator';
import { type GenerationState, getNextAction, isEditing, isGenerating, isItineraryReady, isMultiSpecialistTrip, isStrategyReady } from './planStateHelpers';
import { getTopicLabel } from './stages/StrategyHeroUtils';
import {
  buildDayCardsFingerprint,
  POI_PROMOTION_STABILIZE_MS,
  selectPoiDayCardSnapshot,
  shouldDelayPoiSnapshotPromotion,
} from './strategyStagePoi';
import { useBookingDrawerState } from './useBookingDrawerState';

export type DataDensity = 'empty' | 'ghost' | 'bridge' | 'full';

const MOBILE_PLAN_SCROLL_TO_TOP_EVENT = 'nomadic:mobile-plan-scroll-top';

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
  if (normalizedState === 'P1_ENRICHED' && hasSpecialist && !hasTiles && hasDates) return 'ghost';
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
  const storeTiles = useDocumentStore(useShallow((s) => s.document?.tiles));
  const storeDayCardsRaw = useDocumentStore(useShallow((s) => s.document?.day_cards));
  const toggleTilePreference = useDocumentStore(useShallow((s) => s.toggleTilePreference));
  const isRegenUpdating = useDocumentStore(useShallow((s) => s.isRegenerating));
  const setMobileHeaderCondensed = useUIStore(useShallow((s) => s.setMobileHeaderCondensed));
  const preferredTileIds = useStoreWithEqualityFn(
    useDocumentStore,
    (s) => s.preferredTileIds,
    (a, b) => a.size === b.size && [...a].every((id) => b.has(id))
  );

  const dayCardsFingerprint = useMemo(
    () => buildDayCardsFingerprint(storeDayCardsRaw),
    [storeDayCardsRaw]
  );
  const effectiveTiles = storeTiles ?? tiles;

  const stableDayCardsRef = useRef(storeDayCardsRaw);
  const prevFingerprintRef = useRef(dayCardsFingerprint);
  if (dayCardsFingerprint !== prevFingerprintRef.current) {
    prevFingerprintRef.current = dayCardsFingerprint;
    stableDayCardsRef.current = storeDayCardsRaw;
  }
  const effectiveDayCards = stableDayCardsRef.current ?? viewModel.day_cards;
  const poiStableDayCardsRef = useRef<DayCard[] | null | undefined>(storeDayCardsRaw);
  const poiStableFingerprintRef = useRef<string | null>(dayCardsFingerprint);

  const isAnyRegenerating = isRegenerating || isRegenUpdating;
  const hasSectionData = (viewModel.strategy_sections?.length ?? 0) > 0;
  const isDesktop = useIsDesktop();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isCollapsed = useScrollCollapse(scrollContainerRef, { threshold: 60, hysteresis: 15 });
  const timelineSectionRef = useRef<HTMLDivElement>(null);
  const prevHasItineraryRef = useRef(false);
  const frozenScrollRef = useRef<number | null>(null);

  useEffect(() => {
    if (isDesktop) {
      setMobileHeaderCondensed(false);
      return;
    }
    setMobileHeaderCondensed(isCollapsed);
    return () => {
      setMobileHeaderCondensed(false);
    };
  }, [isCollapsed, isDesktop, setMobileHeaderCondensed]);

  useEffect(() => {
    if (isDesktop) return;

    const handleScrollToTop = () => {
      scrollContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    };

    window.addEventListener(MOBILE_PLAN_SCROLL_TO_TOP_EVENT, handleScrollToTop);
    return () => {
      window.removeEventListener(MOBILE_PLAN_SCROLL_TO_TOP_EVENT, handleScrollToTop);
    };
  }, [isDesktop]);

  useEffect(() => { guardedEnforcePolicy(state, viewModel); }, [state, viewModel]);

  const hasItineraryContent: boolean = isItineraryReady(state) || isEditing(state) ||
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
  const shouldShowAutoProgress = isMultiSpecialist && isStrategyReady(state) && hasDates && generating;
  const hideNextStepBar = isMultiSpecialist && isStrategyReady(state) && hasDates;
  const progressStage: ProgressStage = useMemo(() => {
    if (!generating) return 'success';
    const stage = generation?.stage;
    if (stage === 'itinerary') return 'building';
    if (stage === 'structure' || stage === 'strategy') return 'checking';
    return 'analyzing';
  }, [generating, generation?.stage]);
  const isStreaming = generating || isCommitting || isExpandingItinerary;
  const activeMode: ViewMode = useDocumentStore(useShallow((s) => (s.activeView ?? 'planning') as ViewMode));
  const effectiveMode: ViewMode = explicitMode ?? activeMode;
  const poiSnapshot = selectPoiDayCardSnapshot({
    currentDayCards: storeDayCardsRaw,
    currentFingerprint: dayCardsFingerprint,
    fallbackDayCards: viewModel.day_cards,
    stableDayCards: poiStableDayCardsRef.current,
    stableFingerprint: poiStableFingerprintRef.current,
    isStreaming,
  });
  poiStableDayCardsRef.current = poiSnapshot.nextStableDayCards;
  poiStableFingerprintRef.current = poiSnapshot.nextStableFingerprint;
  const [settledPoiSnapshot, setSettledPoiSnapshot] = useState(() => ({
    dayCards: poiSnapshot.dayCards,
    fingerprint: poiSnapshot.fingerprint,
  }));

  useEffect(() => {
    const nextSnapshot = {
      dayCards: poiSnapshot.dayCards,
      fingerprint: poiSnapshot.fingerprint,
    };
    const snapshotAlreadySettled =
      settledPoiSnapshot.dayCards === nextSnapshot.dayCards &&
      settledPoiSnapshot.fingerprint === nextSnapshot.fingerprint;
    if (
      !shouldDelayPoiSnapshotPromotion({
        settledDayCards: settledPoiSnapshot.dayCards,
        settledFingerprint: settledPoiSnapshot.fingerprint,
        nextFingerprint: poiSnapshot.fingerprint,
        isStreaming,
      })
    ) {
      if (!snapshotAlreadySettled) {
        setSettledPoiSnapshot(nextSnapshot);
      }
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setSettledPoiSnapshot(nextSnapshot);
    }, POI_PROMOTION_STABILIZE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [
    isStreaming,
    poiSnapshot.dayCards,
    poiSnapshot.fingerprint,
    settledPoiSnapshot.dayCards,
    settledPoiSnapshot.fingerprint,
  ]);

  const displayLogic = useMemo(() => {
    const hasDatesLocal = hasDates;
    const hasTilesLocal = effectiveTiles && Object.keys(effectiveTiles).length > 0;
    const density = computeDataDensity(state, viewModel.strategy_sections, effectiveTiles, hasDates);
    const hasDayCardsLocal = (effectiveDayCards?.length ?? 0) > 0;
    const isShowingMirrorLoader = generating && hasDatesLocal && !hasDayCardsLocal;
    let tripDuration = effectiveTripInputs?.trip_duration ?? 3;
    if (effectiveTripInputs?.start_date && effectiveTripInputs?.end_date) {
      const start = new Date(effectiveTripInputs.start_date);
      const end = new Date(effectiveTripInputs.end_date);
      const diffDays = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;
      if (diffDays > 0) tripDuration = diffDays;
    }
    return { hasDates: hasDatesLocal, hasTiles: hasTilesLocal, density, isShowingMirrorLoader, tripDuration };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- effectiveDayCards?.length is captured by dayCardsFingerprint
  }, [state, viewModel.strategy_sections, effectiveTiles, effectiveTripInputs, generating, hasDates, dayCardsFingerprint]);

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
    if (!settledPoiSnapshot.fingerprint) return [];
    const destination = effectiveTripInputs?.destination ?? destinationTitle;
    return extractPOIsFromDayCards(
      settledPoiSnapshot.dayCards ?? undefined,
      specialistData.fullModeSections,
      destination,
      settledPoiSnapshot.fingerprint,
      destinationCoords
    );
  }, [
    settledPoiSnapshot.dayCards,
    settledPoiSnapshot.fingerprint,
    effectiveTripInputs?.destination,
    destinationTitle,
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
