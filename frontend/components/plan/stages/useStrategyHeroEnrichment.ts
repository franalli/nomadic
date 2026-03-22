'use client';

import { useEffect, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import {
  getCachedDestinationIntel,
  getSpecialistEnrichment,
  normalizeDestinationKey,
  setCachedDestinationIntel,
} from '@/lib/destination-intel-cache';
import { useDocumentStore } from '@/state/documentStore';
import type { StrategySection } from '@/types/plan-envelope';

type EnrichmentUiState = 'idle' | 'loading' | 'pending' | 'ready' | 'failed';

interface UseStrategyHeroEnrichmentResult {
  displaySection: StrategySection;
  shouldShowEnrichmentNotice: boolean;
  enrichmentUiState: EnrichmentUiState;
  enrichmentErrorLabel: string;
  handleRetryEnrichment: () => void;
}

export function useStrategyHeroEnrichment(
  section: StrategySection,
  isSheetOpen: boolean
): UseStrategyHeroEnrichmentResult {
  const [enrichedSection, setEnrichedSection] = useState<StrategySection | null>(null);
  const [enrichmentUiState, setEnrichmentUiState] = useState<EnrichmentUiState>('idle');
  const [enrichmentErrorCode, setEnrichmentErrorCode] = useState<string | null>(null);
  const [enrichmentRetryNonce, setEnrichmentRetryNonce] = useState(0);
  const { documentExists, messageSendNonce, storeDestination } = useDocumentStore(
    useShallow((s) => ({
      documentExists: s.document !== null,
      messageSendNonce: s.messageSendNonce,
      storeDestination: s.document?.trip_inputs?.destination ?? null,
    }))
  );

  const displaySection = enrichedSection ?? section;
  const hasTravelIntelligence = Boolean(
    displaySection.travel_intelligence &&
    Object.keys(displaySection.travel_intelligence).length > 0
  );

  useEffect(() => {
    setEnrichedSection(null);
    setEnrichmentUiState('idle');
    setEnrichmentErrorCode(null);
  }, [section.id]);

  useEffect(() => {
    if (!isSheetOpen || section.specialist_type !== 'local_expert') return;
    if (hasTravelIntelligence) {
      setEnrichmentUiState('ready');
      return;
    }

    const destKey = normalizeDestinationKey(storeDestination);
    if (destKey) {
      const cached = getCachedDestinationIntel(destKey);
      if (cached) {
        setEnrichedSection(cached);
        setEnrichmentUiState('ready');
        return;
      }
    }

    const abortController = new AbortController();
    const { signal } = abortController;
    const maxPendingMs = 75_000;
    const startedAt = Date.now();

    const abortableDelay = (ms: number) => {
      if (signal.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
      return new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, ms);
        signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); }, { once: true });
      });
    };

    const run = async () => {
      setEnrichmentUiState('loading');
      setEnrichmentErrorCode(null);
      let transientErrors = 0;
      let pendingAttempts = 0;

      await abortableDelay(3000);

      while (!signal.aborted) {
        let result: Awaited<ReturnType<typeof getSpecialistEnrichment>> = null;
        try {
          result = await getSpecialistEnrichment(section.id);
        } catch {
          transientErrors += 1;
          if (transientErrors >= 3) {
            setEnrichmentUiState('failed');
            setEnrichmentErrorCode('network_error');
            return;
          }
          await abortableDelay(2500);
          continue;
        }
        if (signal.aborted) return;
        transientErrors = 0;

        if (!result) {
          setEnrichmentUiState('failed');
          setEnrichmentErrorCode('not_found');
          return;
        }

        if (result.status === 'ready' && result.data) {
          const enriched = result.data as unknown as StrategySection;
          setEnrichedSection(enriched);
          setEnrichmentUiState('ready');
          if (destKey) setCachedDestinationIntel(destKey, enriched);
          return;
        }

        if (result.status === 'failed') {
          setEnrichmentUiState('failed');
          setEnrichmentErrorCode(result.error_code || 'failed');
          return;
        }

        if (Date.now() - startedAt >= maxPendingMs) {
          setEnrichmentUiState('failed');
          setEnrichmentErrorCode('timeout');
          return;
        }

        setEnrichmentUiState('pending');
        pendingAttempts += 1;
        const suggestedWait = result.retry_after_ms ?? 1500;
        const waitMs = Math.max(2000, Math.min(suggestedWait + pendingAttempts * 150, 5000));
        await abortableDelay(waitMs);
      }
    };

    run().catch((err) => {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!signal.aborted) {
        setEnrichmentUiState('failed');
        setEnrichmentErrorCode('network_error');
      }
    });

    return () => {
      abortController.abort();
    };
  }, [
    documentExists,
    enrichmentRetryNonce,
    hasTravelIntelligence,
    isSheetOpen,
    messageSendNonce,
    section.id,
    section.specialist_type,
    storeDestination,
  ]);

  const handleRetryEnrichment = () => {
    setEnrichmentUiState('idle');
    setEnrichmentErrorCode(null);
    setEnrichmentRetryNonce((n) => n + 1);
  };

  return {
    displaySection,
    shouldShowEnrichmentNotice:
      section.specialist_type === 'local_expert' &&
      !hasTravelIntelligence &&
      ['loading', 'pending', 'failed'].includes(enrichmentUiState),
    enrichmentUiState,
    enrichmentErrorLabel:
      enrichmentErrorCode === 'timeout'
        ? 'Local intelligence timed out. You can retry now.'
        : 'Local intelligence failed to load. You can retry now.',
    handleRetryEnrichment,
  };
}
