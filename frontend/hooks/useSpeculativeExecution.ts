/**
 * Speculative Execution Hook - Pre-loads specialist content during Setup.
 *
 * This hook watches for destination + specialist activity categories and
 * triggers a speculative execution to preload specialist content (diving
 * feasibility, constraints, tips, etc.) before the user clicks "Build Plan".
 *
 * This creates the "Instant AI" feeling - the specialist card appears as
 * soon as the user types "Bali" and selects "Diving".
 *
 * Key features:
 * - 800ms debounce to avoid firing on every keystroke
 * - Abort handling for race conditions (destination changes mid-execution)
 * - Only runs in S0_BOOTSTRAP (Setup) phase
 * - Silent execution - no chat messages appear
 */
import { useEffect, useRef } from 'react';

import { streamGraphPlan } from '@/lib/api';
import { useChatSessionState } from '@/state/chatStore';
import { useDocumentStore, useDocumentTripInputs } from '@/state/documentStore';
import type { PlanDocumentData } from '@/types/document';

const SPECIALIST_CATEGORIES = ['diving', 'hiking', 'skiing', 'cycling', 'sailing'];
const DEBOUNCE_MS = 800;

export function useSpeculativeExecution() {
  const tripInputs = useDocumentTripInputs();
  const sessionState = useChatSessionState();
  const planViewState = useDocumentStore((s) => s.document?.plan_view_state);

  const lastHashRef = useRef<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

  const destination = tripInputs?.destination;
  const categories = tripInputs?.activity_settings?.categories ?? [];

  // 1. CLEANUP: Wipe content if destination changes significantly
  useEffect(() => {
    if (!destination || destination.length < 3) {
      useDocumentStore.getState().clearSpeculativeContent?.();
      lastHashRef.current = null;
    }
  }, [destination]);

  // 2. TRIGGER: Watch inputs with debounce
  useEffect(() => {
    // Only run in Setup Mode (Bootstrap)
    if (planViewState && planViewState !== 'S0_BOOTSTRAP') return;

    // Check prerequisites
    const hasSpecialist = categories.some((c) =>
      SPECIALIST_CATEGORIES.includes(c.toLowerCase())
    );

    if (!destination || destination.length < 3 || !hasSpecialist) return;

    // Clear previous debounce timer
    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(() => {
      // Dedupe by hash (Dest + Categories)
      const hash = `${destination}_${categories.sort().join(',')}`;
      if (hash === lastHashRef.current) return;
      lastHashRef.current = hash;

      // Abort previous in-flight request
      if (abortRef.current) {
        abortRef.current();
      }

      // Fire speculative request
      console.log('[Speculative] Firing speculative request...');
      abortRef.current = streamGraphPlan(
        {
          message: 'SPECULATE_SPECIALISTS',
          session_state: sessionState ?? undefined,
          trip_inputs: tripInputs as Record<string, unknown>,
        },
        {
          onToken: () => {
            // Ignore tokens - we only care about the final result
          },
          onComplete: (response) => {
            const doc = response.document as PlanDocumentData | undefined;
            const sections = doc?.strategy_sections;
            if (sections && sections.length > 0) {
              console.log('[Speculative] Content received, merging...');
              useDocumentStore.getState().mergeSpeculativeContent?.(sections);
            }
          },
          onError: (err) => {
            // Silent fail - speculative is best-effort
            if (err.message !== 'The user aborted a request.') {
              console.warn('[Speculative] Silent failure:', err);
            }
          },
        }
      );
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [destination, categories, planViewState, sessionState, tripInputs]);
}
