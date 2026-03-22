'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import type { SpecialistType } from '@/lib/specialistLinkParser';
import { useMobileNavStore } from '@/state/mobileNavStore';

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

/** Delay before scrolling to allow tab animation to complete */
const TAB_TRANSITION_DELAY_MS = 300;

/** Duration of highlight animation */
const HIGHLIGHT_DURATION_MS = 2000;

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * useSpecialistDeepLink - Hook for navigating to specialist cards from chat.
 *
 * On mobile: Switches to Plan tab, then scrolls to the specialist card.
 * On desktop: Just scrolls to the specialist card in the right panel.
 *
 * @example
 * const { navigateToSpecialist } = useSpecialistDeepLink();
 * navigateToSpecialist('diving'); // Scrolls to Diving Specialist card
 */
export function useSpecialistDeepLink() {
  const isDesktop = useIsDesktop();
  const scrollTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    };
  }, []);

  const navigateToSpecialist = useCallback(
    (specialistType: SpecialistType) => {
      // On mobile, navigate to Plan page first
      if (!isDesktop) {
        useMobileNavStore.getState().navigateToPlan();
      }

      // Clear any pending timeouts from previous navigation
      if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);

      // Wait for tab transition animation, then scroll
      scrollTimeoutRef.current = setTimeout(() => {
        // Find the specialist card by data-topic attribute
        // AgentCards have data-topic="diving", data-topic="hiking", etc.
        const card = document.querySelector(`[data-topic="${specialistType}"]`);

        if (card) {
          // Scroll to the card
          card.scrollIntoView({ behavior: 'smooth', block: 'center' });

          // Add highlight animation class
          card.classList.add('specialist-highlight');

          // Remove highlight after animation completes
          highlightTimeoutRef.current = setTimeout(() => {
            card.classList.remove('specialist-highlight');
          }, HIGHLIGHT_DURATION_MS);
        } else {
          // Card not found - might be collapsed or not rendered yet
          // Try scrolling to the strategy section instead
          const strategySection = document.querySelector('[data-strategy-section]');
          strategySection?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }, isDesktop ? 0 : TAB_TRANSITION_DELAY_MS);
    },
    [isDesktop]
  );

  return useMemo(() => ({ navigateToSpecialist }), [navigateToSpecialist]);
}
