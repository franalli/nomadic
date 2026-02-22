/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * mobileNavStore - Zustand store for mobile horizontal page navigation.
 *
 * Controls the two-page swipe layout (Chat ↔ Plan).
 *
 * Pages:
 *   0 = Chat (default)
 *   1 = Plan
 */

import { create } from 'zustand';

export type MobilePage = 0 | 1;

interface MobileNavState {
  /** Current visible page (0=chat, 1=plan) */
  activePage: MobilePage;
  /** Badge: plan has new unread content */
  hasNewPlanContent: boolean;
  /** Set active page (from user swipe or tab tap) */
  setActivePage: (page: MobilePage) => void;
  /** Navigate to plan page + clear badge */
  navigateToPlan: () => void;
  /** Navigate to chat page */
  navigateToChat: () => void;
  /** Mark plan as having new content (badge dot) */
  setHasNewPlanContent: (has: boolean) => void;
  /** Reset to initial state (on session reset) */
  reset: () => void;
}

export const useMobileNavStore = create<MobileNavState>((set, get) => ({
  activePage: 0,
  hasNewPlanContent: false,
  setActivePage: (page) => {
    if (get().activePage === page) return;
    const updates: Partial<MobileNavState> = { activePage: page };
    if (page === 1) updates.hasNewPlanContent = false;
    set(updates);
  },
  navigateToPlan: () => set({ activePage: 1, hasNewPlanContent: false }),
  navigateToChat: () => set({ activePage: 0 }),
  setHasNewPlanContent: (has) => set({ hasNewPlanContent: has }),
  reset: () => set({ activePage: 0, hasNewPlanContent: false }),
}));
