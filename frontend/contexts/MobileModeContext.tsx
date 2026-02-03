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

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type MobileMode = 'planner' | 'plan';

interface MobileModeContextValue {
  /** Current mobile mode ('planner' or 'plan'). Only relevant when isDesktop is false. */
  mode: MobileMode;
  /** True if viewport is >= 1024px (lg breakpoint). When true, both panels are visible. */
  isDesktop: boolean;
  /** Switch to Plan Mode (mobile only). Preserves current mode if already on desktop. */
  switchToPlan: () => void;
  /** Switch to Planner Mode (mobile only). Restores Plan scroll position on next switch. */
  switchToPlanner: () => void;

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

// ─────────────────────────────────────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────────────────────────────────────

interface MobileModeProviderProps {
  children: React.ReactNode;
  /** Optional: Override initial mode for testing */
  initialMode?: MobileMode;
}

export function MobileModeProvider({
  children,
  initialMode = 'planner',
}: MobileModeProviderProps) {
  // Default to desktop for SSR to avoid hydration mismatch
  const [isDesktop, setIsDesktop] = useState(true);
  const [mode, setMode] = useState<MobileMode>(initialMode);

  // Setup Drawer State
  const [isSetupDrawerOpen, setIsSetupDrawerOpen] = useState(false);

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

  // Switch to Plan Mode
  const switchToPlan = useCallback(() => {
    setMode('plan');

    // Restore scroll position after render
    requestAnimationFrame(() => {
      const planView = document.querySelector('[data-testid="plan-view"]');
      if (planView && planScrollPositionRef.current > 0) {
        planView.scrollTop = planScrollPositionRef.current;
      }
    });
  }, []);

  // Switch to Planner Mode
  const switchToPlanner = useCallback(() => {
    // Capture current Plan scroll position before switching
    const planView = document.querySelector('[data-testid="plan-view"]');
    if (planView) {
      planScrollPositionRef.current = planView.scrollTop;
    }

    setMode('planner');
  }, []);

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
