'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import type { ViewName } from '@/hooks/useViewNavigation';
import { useDocumentStore } from '@/state/documentStore';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type MobileMode = 'planner' | 'plan';
export type MobileTab = 'chat' | 'plan' | 'book';

interface MobileModeContextValue {
  /** Current mobile mode ('planner' or 'plan'). Only relevant when isDesktop is false. */
  mode: MobileMode;
  /** True if viewport is >= 1024px (lg breakpoint). When true, both panels are visible. */
  isDesktop: boolean;
  /** Switch to Plan Mode (mobile only). Preserves current mode if already on desktop. */
  switchToPlan: () => void;
  /** Switch to Planner Mode (mobile only). Restores Plan scroll position on next switch. */
  switchToPlanner: () => void;

  // 3-Tab Navigation System
  /** Current active tab on mobile ('chat' | 'plan' | 'book') */
  activeTab: MobileTab;
  /** Set the active tab on mobile */
  setActiveTab: (tab: MobileTab) => void;
  /** Whether the Plan tab has unread updates (shows badge) */
  planTabHasUpdate: boolean;
  /** Set whether Plan tab has unread updates */
  setPlanTabHasUpdate: (hasUpdate: boolean) => void;

  // Setup Drawer
  /** Whether the setup drawer is open (mobile header accordion) */
  isSetupDrawerOpen: boolean;
  /** Toggle the setup drawer open/closed */
  toggleSetupDrawer: () => void;
  /** Close the setup drawer */
  closeSetupDrawer: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────────────────────────────────────

const MobileModeContext = createContext<MobileModeContextValue | null>(null);

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const DESKTOP_BREAKPOINT = 1024; // lg breakpoint in Tailwind
const MEDIA_QUERY = `(min-width: ${DESKTOP_BREAKPOINT}px)`;

// Mapping between mobile tabs and document views (for bi-directional sync)
const TAB_TO_VIEW: Record<MobileTab, ViewName> = {
  chat: 'setup',
  plan: 'plan',
  book: 'book',
};
const VIEW_TO_TAB: Record<ViewName, MobileTab> = {
  setup: 'chat',
  plan: 'plan',
  book: 'book',
};

// ─────────────────────────────────────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────────────────────────────────────

interface MobileModeProviderProps {
  children: React.ReactNode;
  /** Optional: Override initial mode for testing */
  initialMode?: MobileMode;
  /** Optional: Override initial tab for testing */
  initialTab?: MobileTab;
}

export function MobileModeProvider({
  children,
  initialMode = 'planner',
  initialTab = 'chat',
}: MobileModeProviderProps) {
  // Default to desktop for SSR to avoid hydration mismatch
  const [isDesktop, setIsDesktop] = useState(true);
  const [mode, setMode] = useState<MobileMode>(initialMode);

  // 3-Tab Navigation State
  const [activeTab, setActiveTabState] = useState<MobileTab>(initialTab);
  const [planTabHasUpdate, setPlanTabHasUpdate] = useState(false);

  // Setup Drawer State
  const [isSetupDrawerOpen, setIsSetupDrawerOpen] = useState(false);

  // Document store - for bi-directional view sync
  const documentActiveView = useDocumentStore((s) => s.activeView);
  const setDocumentActiveView = useDocumentStore((s) => s.setActiveView);

  // Store Plan View scroll position for restoration
  const planScrollPositionRef = useRef(0);

  // Viewport detection via matchMedia
  useEffect(() => {
    // Check if window is available (client-side only)
    if (typeof window === 'undefined') return;

    const mediaQuery = window.matchMedia(MEDIA_QUERY);

    // Set initial value
    setIsDesktop(mediaQuery.matches);

    // Listen for changes
    const handleChange = (e: MediaQueryListEvent) => {
      setIsDesktop(e.matches);
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // Bi-directional sync: documentStore.activeView → mobile activeTab
  useEffect(() => {
    const targetTab = VIEW_TO_TAB[documentActiveView];
    // SAFETY GUARD: Only update if strictly different to prevent feedback loop
    if (targetTab && targetTab !== activeTab) {
      setActiveTabState(targetTab);
      // Also sync legacy mode
      setMode(targetTab === 'chat' ? 'planner' : 'plan');
    }
  }, [documentActiveView, activeTab]);

  // Switch to Plan Mode (legacy - also sets activeTab)
  const switchToPlan = useCallback(() => {
    setMode('plan');
    setActiveTabState('plan');

    // Restore scroll position after render
    requestAnimationFrame(() => {
      const planView = document.querySelector('[data-testid="plan-view"]');
      if (planView && planScrollPositionRef.current > 0) {
        planView.scrollTop = planScrollPositionRef.current;
      }
    });
  }, []);

  // Switch to Planner Mode (legacy - also sets activeTab)
  const switchToPlanner = useCallback(() => {
    // Capture current Plan scroll position before switching
    const planView = document.querySelector('[data-testid="plan-view"]');
    if (planView) {
      planScrollPositionRef.current = planView.scrollTop;
    }

    setMode('planner');
    setActiveTabState('chat');
  }, []);

  // Set active tab (3-tab system) - also syncs legacy mode and document store
  const setActiveTab = useCallback((tab: MobileTab) => {
    // Capture scroll position when leaving plan/book
    if (activeTab === 'plan' || activeTab === 'book') {
      const planView = document.querySelector('[data-testid="plan-view"]');
      if (planView) {
        planScrollPositionRef.current = planView.scrollTop;
      }
    }

    setActiveTabState(tab);

    // Sync to document store (bi-directional sync)
    setDocumentActiveView(TAB_TO_VIEW[tab]);

    // Sync legacy mode: chat -> planner, plan/book -> plan
    setMode(tab === 'chat' ? 'planner' : 'plan');

    // Restore scroll when entering plan tab
    if (tab === 'plan') {
      requestAnimationFrame(() => {
        const planView = document.querySelector('[data-testid="plan-view"]');
        if (planView && planScrollPositionRef.current > 0) {
          planView.scrollTop = planScrollPositionRef.current;
        }
      });
    }
  }, [activeTab, setDocumentActiveView]);

  // Setup Drawer Controls
  const toggleSetupDrawer = useCallback(() => {
    console.log('[MobileModeContext] toggleSetupDrawer called, current state:', isSetupDrawerOpen);
    setIsSetupDrawerOpen((prev) => {
      console.log('[MobileModeContext] Setting isSetupDrawerOpen from', prev, 'to', !prev);
      return !prev;
    });
  }, [isSetupDrawerOpen]);

  const closeSetupDrawer = useCallback(() => {
    setIsSetupDrawerOpen(false);
  }, []);

  const value = useMemo<MobileModeContextValue>(
    () => ({
      mode,
      isDesktop,
      switchToPlan,
      switchToPlanner,
      // 3-Tab Navigation
      activeTab,
      setActiveTab,
      planTabHasUpdate,
      setPlanTabHasUpdate,
      // Setup Drawer
      isSetupDrawerOpen,
      toggleSetupDrawer,
      closeSetupDrawer,
    }),
    [
      mode,
      isDesktop,
      switchToPlan,
      switchToPlanner,
      activeTab,
      setActiveTab,
      planTabHasUpdate,
      isSetupDrawerOpen,
      toggleSetupDrawer,
      closeSetupDrawer,
    ]
  );

  return (
    <MobileModeContext.Provider value={value}>
      {children}
    </MobileModeContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Hook to access mobile mode state and actions.
 *
 * @example
 * const { mode, isDesktop, switchToPlan, switchToPlanner } = useMobileMode();
 *
 * // On mobile: conditionally render based on mode
 * if (!isDesktop && mode === 'planner') {
 *   return <PlannerView />;
 * }
 *
 * // On mobile: switch modes
 * <button onClick={switchToPlan}>Generate plan</button>
 * <button onClick={switchToPlanner}>← Edit</button>
 */
export function useMobileMode(): MobileModeContextValue {
  const context = useContext(MobileModeContext);

  if (!context) {
    throw new Error('useMobileMode must be used within a MobileModeProvider');
  }

  return context;
}

// ─────────────────────────────────────────────────────────────────────────────
// Convenience Hooks
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Returns true if currently in Planner Mode on mobile.
 * Always false on desktop (both panels visible).
 */
export function useIsPlannerMode(): boolean {
  const { mode, isDesktop } = useMobileMode();
  return !isDesktop && mode === 'planner';
}

/**
 * Returns true if currently in Plan Mode on mobile.
 * Always false on desktop (both panels visible).
 */
export function useIsPlanMode(): boolean {
  const { mode, isDesktop } = useMobileMode();
  return !isDesktop && mode === 'plan';
}

/**
 * Returns true if the specified tab is currently active on mobile.
 * Always false on desktop (all content visible in split view).
 */
export function useIsActiveTab(tab: MobileTab): boolean {
  const { activeTab, isDesktop } = useMobileMode();
  return !isDesktop && activeTab === tab;
}

/**
 * Returns true if currently on Chat tab on mobile.
 */
export function useIsChatTab(): boolean {
  return useIsActiveTab('chat');
}

/**
 * Returns true if currently on Plan tab on mobile.
 */
export function useIsPlanTab(): boolean {
  return useIsActiveTab('plan');
}

/**
 * Returns true if currently on Book tab on mobile.
 */
export function useIsBookTab(): boolean {
  return useIsActiveTab('book');
}
