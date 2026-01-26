'use client';

import { useCallback } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import type { SpecialistType } from '@/lib/specialistLinkParser';

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
  const { setActiveTab, isDesktop } = useMobileMode();

  const navigateToSpecialist = useCallback(
    (specialistType: SpecialistType) => {
      // On mobile, switch to Plan tab first
      if (!isDesktop) {
        setActiveTab('plan');
      }

      // Wait for tab transition animation, then scroll
      setTimeout(() => {
        // Find the specialist card by data-topic attribute
        // AgentCards have data-topic="diving", data-topic="hiking", etc.
        const card = document.querySelector(`[data-topic="${specialistType}"]`);

        if (card) {
          // Scroll to the card
          card.scrollIntoView({ behavior: 'smooth', block: 'center' });

          // Add highlight animation class
          card.classList.add('specialist-highlight');

          // Remove highlight after animation completes
          setTimeout(() => {
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
    [setActiveTab, isDesktop]
  );

  return { navigateToSpecialist };
}
