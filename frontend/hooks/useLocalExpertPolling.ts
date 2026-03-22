'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import {
  deleteInflight,
  getCachedDestinationIntel,
  getInflight,
  getSpecialistEnrichment,
  normalizeDestinationKey,
  setCachedDestinationIntel,
  setInflight,
} from '@/lib/destination-intel-cache';
import type { IntelCategory } from '@/lib/travelIntel';
import { buildDestinationIntel } from '@/lib/travelIntel';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { StrategySection } from '@/types/plan-envelope';

// ---------------------------------------------------------------------------
// Helpers (pure functions, previously inline in PlanFullDensityView)
// ---------------------------------------------------------------------------

function localExpertEnrichmentState(section: StrategySection | undefined): string {
  const raw = section?.local_expert_enrichment?.state;
  if (typeof raw !== 'string') return '';
  return raw.trim().toLowerCase();
}

function sectionFingerprint(section: StrategySection | null | undefined): string {
  if (!section) return '';
  const enrichment = section.local_expert_enrichment;
  const updatedAt = typeof enrichment?.updated_at === 'string' ? enrichment.updated_at : '';
  const enrichmentState = typeof enrichment?.state === 'string' ? enrichment.state : '';
  return [
    section.id ?? '',
    enrichmentState,
    updatedAt,
    section.constraints_applied?.length ?? 0,
    section.content_added?.length ?? 0,
    section.travel_intelligence ? Object.keys(section.travel_intelligence).length : 0,
  ].join('|');
}

// ---------------------------------------------------------------------------
// Hook interface
// ---------------------------------------------------------------------------

interface UseLocalExpertPollingParams {
  strategySections: StrategySection[];
  effectiveFullDest: string | undefined;
  isStreaming: boolean;
  localExpertSectionId: string | null;
  localExpertReady: boolean;
  localExpertHasTI: boolean;
  localExpertSection: StrategySection | undefined;
}

interface UseLocalExpertPollingResult {
  effectiveStrategySections: StrategySection[];
  intelCategories: IntelCategory[];
  travelIntelItemCount: number;
  isTravelIntelPending: boolean;
  hasDestinationIntel: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useLocalExpertPolling({
  strategySections,
  effectiveFullDest,
  isStreaming,
  localExpertSectionId,
  localExpertReady,
  localExpertHasTI,
  localExpertSection,
}: UseLocalExpertPollingParams): UseLocalExpertPollingResult {
  const intelDestinationKey = normalizeDestinationKey(effectiveFullDest);

  const localExpertSectionRef = useRef<StrategySection | null>(null);

  // Track streaming state in a ref so the enrichment polling loop can
  // bail out when a new graph request starts (props are stale in closures).
  const isStreamingRef = useRef(isStreaming);
  // Monotonic turn counter — increments each time streaming starts.
  // Polling loops capture the value at start and bail if it changes,
  // closing the 0-500ms race window between "user sends" and "first SSE event".
  const turnCounterRef = useRef(0);
  useEffect(() => {
    isStreamingRef.current = isStreaming;
    if (isStreaming) turnCounterRef.current += 1;
  }, [isStreaming]);

  const [enrichedLocalExpertSection, setEnrichedLocalExpertSection] = useState<StrategySection | null>(null);

  const effectiveStrategySections = useMemo(() => {
    if (!localExpertSectionId || !enrichedLocalExpertSection) {
      return strategySections;
    }
    return strategySections.map((section) => {
      if (section.id !== localExpertSectionId) return section;
      return { ...section, ...enrichedLocalExpertSection };
    });
  }, [enrichedLocalExpertSection, localExpertSectionId, strategySections]);

  const { categories: intelCategories, tipCount: travelIntelItemCount } = useMemo(
    () => buildDestinationIntel(effectiveStrategySections),
    [effectiveStrategySections]
  );

  const effectiveLocalExpertSection = useMemo(
    () => effectiveStrategySections.find((s) => s.specialist_type === 'local_expert'),
    [effectiveStrategySections]
  );
  const enrichmentStillPending = localExpertEnrichmentState(effectiveLocalExpertSection) === 'pending';
  // Only show spinner when truly no data yet — once we have categories, stop spinning
  const isTravelIntelPending = enrichmentStillPending && intelCategories.length === 0;
  const hasDestinationIntel = intelCategories.length > 0;

  // Reset enriched section when destination or section ID changes
  useEffect(() => {
    setEnrichedLocalExpertSection(null);
  }, [intelDestinationKey, localExpertSectionId]);

  // Keep localExpertSectionRef in sync
  useEffect(() => {
    localExpertSectionRef.current = localExpertSection ?? null;
  }, [localExpertSection]);

  // Main polling effect
  useEffect(() => {
    if (!localExpertSectionId || !intelDestinationKey) return;
    let cancelled = false;

    const applySectionUpdate = (enriched: StrategySection) => {
      if (cancelled) return;
      setEnrichedLocalExpertSection((current) => (
        sectionFingerprint(current) === sectionFingerprint(enriched) ? current : enriched
      ));
    };

    const sourceSection = localExpertSectionRef.current;
    if (localExpertReady && localExpertHasTI && sourceSection) {
      setCachedDestinationIntel(intelDestinationKey, sourceSection);
      applySectionUpdate(sourceSection);
      return () => {
        cancelled = true;
      };
    }

    const cached = getCachedDestinationIntel(intelDestinationKey);
    if (cached) {
      applySectionUpdate(cached);
      return () => {
        cancelled = true;
      };
    }

    const run = async () => {
      const maxPendingMs = 20_000;
      const startedAt = Date.now();
      let pendingAttempts = 0;
      let transientErrors = 0;
      const startTurn = turnCounterRef.current;

      // Brief initial delay before first poll
      await new Promise((resolve) => setTimeout(resolve, 1500));
      if (cancelled) return;

      while (!cancelled) {
        // Abandon polling when a new graph request starts — fresh
        // enrichment data will arrive with the new response.
        if (isStreamingRef.current || turnCounterRef.current !== startTurn) return;

        let result: Awaited<ReturnType<typeof getSpecialistEnrichment>> = null;
        try {
          result = await getSpecialistEnrichment(localExpertSectionId);
        } catch {
          if (cancelled) return;
          transientErrors += 1;
          if (transientErrors >= 3) return;
          await new Promise((resolve) => setTimeout(resolve, 2000));
          continue;
        }
        if (cancelled || isStreamingRef.current || turnCounterRef.current !== startTurn) return;
        transientErrors = 0;
        if (!result) return;

        if (result.status === 'ready' && result.data) {
          const enriched = result.data as unknown as StrategySection;
          setCachedDestinationIntel(intelDestinationKey, enriched);
          applySectionUpdate(enriched);
          return;
        }

        if (result.status === 'failed') return;
        if (Date.now() - startedAt >= maxPendingMs) return;

        pendingAttempts += 1;
        const suggestedWait = result.retry_after_ms ?? 1500;
        const waitMs = Math.max(1500, Math.min(suggestedWait + pendingAttempts * 150, 5000));
        await new Promise((resolve) => setTimeout(resolve, waitMs));
      }
    };

    const startPolling = (): Promise<void> => {
      const inflight = run().finally(() => {
        deleteInflight(intelDestinationKey);
      });
      setInflight(intelDestinationKey, inflight);
      return inflight;
    };

    const existingInflight = getInflight(intelDestinationKey);
    if (existingInflight) {
      void existingInflight.finally(() => {
        if (cancelled) return;
        const fromCache = getCachedDestinationIntel(intelDestinationKey);
        if (fromCache) {
          applySectionUpdate(fromCache);
          return;
        }
        // If an older in-flight poll completed without populating cache
        // (e.g. cancelled during StrictMode remount), kick off one fresh poll.
        if (!getInflight(intelDestinationKey)) {
          void startPolling();
        }
      });
      return () => {
        cancelled = true;
      };
    }

    void startPolling();

    return () => {
      cancelled = true;
    };
  }, [
    intelDestinationKey,
    localExpertHasTI,
    localExpertReady,
    localExpertSectionId,
  ]);

  // Sync travel advice data to panel toggle store
  const showTravelAdviceSegment = hasDestinationIntel || isTravelIntelPending;
  useEffect(() => {
    usePanelToggleStore.getState().setTravelAdviceData({
      count: travelIntelItemCount,
      show: showTravelAdviceSegment,
      pending: isTravelIntelPending,
    });
  }, [travelIntelItemCount, showTravelAdviceSegment, isTravelIntelPending]);

  return useMemo(() => ({
    effectiveStrategySections,
    intelCategories,
    travelIntelItemCount,
    isTravelIntelPending,
    hasDestinationIntel,
  }), [effectiveStrategySections, intelCategories, travelIntelItemCount, isTravelIntelPending, hasDestinationIntel]);
}
