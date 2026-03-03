'use client';

/**
 * useLandingEffects
 *
 * Side-effect-only useEffects for NomadicLanding that don't belong
 * to itinerary generation. Manages destination image fetching,
 * hasEverHadPlan detection, topic tracking, mobile badges, etc.
 *
 * State (hasEverHadPlan, localPendingTopics, destinationImageUrl) is
 * owned by the parent component and passed in as params + setters.
 * This avoids a circular dependency with useLandingDerived.
 */

import { useEffect, useMemo, useRef } from 'react';

import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import { isFraming } from '@/components/plan/planStateHelpers';
import { getTopicLabel } from '@/components/plan/stages/StrategyHeroUtils';
import { useSpecialistDeepLink } from '@/hooks/useSpecialistDeepLink';
import { fetchDestinationImage } from '@/lib/api';
import type { SpecialistType } from '@/lib/specialistLinkParser';
import { useMobileNavStore } from '@/state/mobileNavStore';
import type { DocumentTripInputs } from '@/types/document';
import type { PlanViewState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface UseLandingEffectsParams {
  tripInputs: DocumentTripInputs;
  planViewState: PlanViewState;
  docExecutedTopics: string[] | undefined;
  hasBranchesReady: boolean;
  hasStrategyContent: boolean;
  hasTilesReady: boolean;
  hasDayCardsReady: boolean;
  userRequestedGeneration: boolean;
  docTileCount: number;
  isDesktop: boolean;
  hasDates: boolean;
  canViewPlan: boolean;
  activeView: string;
  setActiveView: (view: 'planning' | 'booking') => void;
  toast: (message: string, options?: { type?: 'success' | 'info' | 'warning' | 'error' }) => void;
  mobileNavigateToPlan: () => void;
  mobileSetHasNewContent: (v: boolean) => void;
  tripInputsEditor: ReturnType<typeof useTripInputsEditor>;

  // State owned by parent, managed by effects
  hasEverHadPlan: boolean;
  setHasEverHadPlan: (v: boolean) => void;
  setLocalPendingTopics: React.Dispatch<React.SetStateAction<string[]>>;
  setDestinationImageUrl: (url: string | null) => void;
  /** When true, session is still being restored — skip side-effects that may be wasted */
  isHydrating?: boolean;
}

export interface UseLandingEffectsResult {
  tripInputsEditorRef: React.MutableRefObject<ReturnType<typeof useTripInputsEditor> | null>;
  finalizeTimerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useLandingEffects({
  tripInputs,
  planViewState,
  docExecutedTopics,
  hasBranchesReady,
  hasStrategyContent,
  hasTilesReady,
  hasDayCardsReady,
  userRequestedGeneration,
  docTileCount,
  isDesktop,
  hasDates,
  canViewPlan,
  activeView,
  setActiveView,
  toast,
  mobileNavigateToPlan,
  mobileSetHasNewContent,
  tripInputsEditor,
  hasEverHadPlan,
  setHasEverHadPlan,
  setLocalPendingTopics,
  setDestinationImageUrl,
  isHydrating,
}: UseLandingEffectsParams): UseLandingEffectsResult {
  // ─── Destination image fetch ────────────────────────────────────────────

  const lastFetchedDestination = useRef<string | null>(null);

  useEffect(() => {
    const destination = tripInputs.destination;
    if (!destination || destination === lastFetchedDestination.current) return;
    if (isHydrating) return;

    lastFetchedDestination.current = destination;
    setDestinationImageUrl(null);

    const controller = new AbortController();

    fetchDestinationImage(destination, { signal: controller.signal })
      .then((res) => {
        if (
          !controller.signal.aborted &&
          lastFetchedDestination.current === destination
        ) {
          setDestinationImageUrl(res.image_url);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          console.error('Failed to fetch destination image:', err);
        }
      });

    return () => controller.abort();
  }, [tripInputs.destination, setDestinationImageUrl, isHydrating]);

  // ─── hasEverHadPlan detection ───────────────────────────────────────────

  useEffect(() => {
    if (
      hasBranchesReady &&
      hasStrategyContent &&
      !hasEverHadPlan &&
      userRequestedGeneration
    ) {
      setHasEverHadPlan(true);
    }
    if (hasTilesReady && !hasEverHadPlan) {
      setHasEverHadPlan(true);
    }
    if (hasDayCardsReady && !hasEverHadPlan) {
      setHasEverHadPlan(true);
    }
  }, [
    hasBranchesReady,
    hasStrategyContent,
    hasEverHadPlan,
    userRequestedGeneration,
    hasTilesReady,
    hasDayCardsReady,
    setHasEverHadPlan,
  ]);

  // ─── Auto-swipe to Plan on first content (one-shot) ───────────────────

  const didAutoSwipeRef = useRef(false);
  const hasPlanContent = hasStrategyContent || hasTilesReady || hasDayCardsReady;
  useEffect(() => {
    if (isDesktop || isHydrating) return;

    // Session reset / fresh draft: allow auto-swipe again for the next first content.
    if (!hasPlanContent) {
      didAutoSwipeRef.current = false;
      return;
    }

    const { activePage } = useMobileNavStore.getState();
    if (!didAutoSwipeRef.current && activePage === 0) {
      didAutoSwipeRef.current = true;
      mobileNavigateToPlan();
    }
  }, [hasPlanContent, isDesktop, isHydrating, mobileNavigateToPlan]);

  // ─── Local pending topics ──────────────────────────────────────────────

  // Clear local pending topics when backend responds with executed_strategy_topics
  const executedTopics = useMemo(() => docExecutedTopics ?? [], [docExecutedTopics]);
  useEffect(() => {
    if (executedTopics.length > 0) {
      setLocalPendingTopics((prev) =>
        prev.filter((topic) => !executedTopics.includes(topic))
      );
    }
  }, [executedTopics, setLocalPendingTopics]);

  // Badge notification: Track when specialists update
  const lastSeenTopicsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const executed = new Set(executedTopics);
    const newTopics = [...executed].filter((t) => !lastSeenTopicsRef.current.has(t));
    const hasNew = newTopics.length > 0;
    if (hasNew) {
      const topicLabel = getTopicLabel(newTopics[0]);
      toast(`Plan Updated: ${topicLabel} Strategy Added`);
      lastSeenTopicsRef.current = executed;
    }
  }, [executedTopics, toast]);

  // ─── Auto-switch to Plan view when framing ─────────────────────────────

  useEffect(() => {
    if (isFraming(planViewState)) {
      if (!isDesktop) {
        mobileNavigateToPlan();
      }
      setActiveView('planning');
    }
  }, [isDesktop, planViewState, mobileNavigateToPlan, setActiveView]);

  // ─── Mobile badge: plan content updated while user is on chat page ─────

  const tileCount = docTileCount;
  const prevTileCountRef = useRef(0);
  useEffect(() => {
    const mobileActivePage = useMobileNavStore.getState().activePage;
    if (!isDesktop && mobileActivePage === 0 && tileCount > prevTileCountRef.current) {
      mobileSetHasNewContent(true);
    }
    prevTileCountRef.current = tileCount;
  }, [isDesktop, tileCount, mobileSetHasNewContent]);

  // ─── Specialist deep link navigation ───────────────────────────────────

  const { navigateToSpecialist } = useSpecialistDeepLink();
  useEffect(() => {
    const handleSpecialistNavigate = (event: Event) => {
      const customEvent = event as CustomEvent<{ specialistType: string }>;
      navigateToSpecialist(customEvent.detail.specialistType as SpecialistType);
    };
    window.addEventListener('specialist-navigate', handleSpecialistNavigate);
    return () => {
      window.removeEventListener('specialist-navigate', handleSpecialistNavigate);
    };
  }, [navigateToSpecialist]);

  // ─── Auto-transition when dates set ────────────────────────────────────

  useEffect(() => {
    if (hasDates && canViewPlan && activeView === 'setup') {
      if (!isDesktop) {
        mobileSetHasNewContent(true);
      }
      setActiveView('planning');
    }
  }, [
    hasDates,
    canViewPlan,
    activeView,
    isDesktop,
    mobileSetHasNewContent,
    setActiveView,
  ]);

  // ─── Finalize timer cleanup ────────────────────────────────────────────

  const finalizeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (finalizeTimerRef.current) clearTimeout(finalizeTimerRef.current);
  }, []);

  // ─── tripInputsEditorRef sync ──────────────────────────────────────────

  const tripInputsEditorRef = useRef<ReturnType<typeof useTripInputsEditor> | null>(null);
  useEffect(() => {
    tripInputsEditorRef.current = tripInputsEditor;
  }, [tripInputsEditor]);

  return {
    tripInputsEditorRef,
    finalizeTimerRef,
  };
}
