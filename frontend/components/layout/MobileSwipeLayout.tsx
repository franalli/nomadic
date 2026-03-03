'use client';

/**
 * MobileSwipeLayout - Horizontal two-page swipe layout for mobile.
 *
 * Uses CSS scroll-snap for native-feeling page transitions.
 * Zero dependencies — no vaul, no framer-motion.
 *
 * Page 0: Chat (always starts here)
 * Page 1: Plan (auto-navigates when content arrives)
 *
 * Includes a compact tab bar with badge indicator.
 */

import { memo, useCallback, useEffect, useRef } from 'react';

import { cn } from '@/lib/utils';
import { type MobilePage, useMobileNavStore } from '@/state/mobileNavStore';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MobileSwipeLayoutProps {
  chatContent: React.ReactNode;
  planContent: React.ReactNode;
  /** Whether Plan tab is unlocked (plan content exists). When false, tab is disabled and swipe is blocked. */
  planTabEnabled?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function MobileSwipeLayoutInner({ chatContent, planContent, planTabEnabled = false }: MobileSwipeLayoutProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const swipeResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activePage = useMobileNavStore((s) => s.activePage);
  const hasNewPlanContent = useMobileNavStore((s) => s.hasNewPlanContent);
  const setActivePage = useMobileNavStore((s) => s.setActivePage);
  const isProgrammatic = useRef(false);

  // Programmatic scroll when activePage changes from store
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // Don't navigate to Plan if tab is locked
    if (activePage === 1 && !planTabEnabled) return;
    const targetLeft = activePage * el.clientWidth;
    if (Math.abs(targetLeft - el.scrollLeft) > 10) {
      isProgrammatic.current = true;
      el.scrollTo({ left: targetLeft, behavior: 'smooth' });
      const timer = setTimeout(() => {
        isProgrammatic.current = false;
      }, 400);
      return () => clearTimeout(timer);
    }
  }, [activePage, planTabEnabled]);

  // Detect user swipe via scroll position
  const handleScroll = useCallback(() => {
    if (isProgrammatic.current) return;
    const el = containerRef.current;
    if (!el || el.clientWidth === 0) return;
    const raw = Math.round(el.scrollLeft / el.clientWidth);
    const page = Math.max(0, Math.min(1, raw)) as MobilePage;
    // Block swipe to Plan when tab is locked
    if (page === 1 && !planTabEnabled) {
      isProgrammatic.current = true;
      el.scrollTo({ left: 0, behavior: 'smooth' });
      swipeResetTimeoutRef.current = setTimeout(() => { isProgrammatic.current = false; }, 400);
      return;
    }
    if (page !== useMobileNavStore.getState().activePage) {
      setActivePage(page);
    }
  }, [setActivePage, planTabEnabled]);

  useEffect(() => {
    return () => {
      if (swipeResetTimeoutRef.current) clearTimeout(swipeResetTimeoutRef.current);
    };
  }, []);

  // Tab tap handler
  const goToPage = useCallback(
    (page: MobilePage) => {
      setActivePage(page);
    },
    [setActivePage]
  );

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-3 py-1 border-b border-zinc-200 dark:border-white/10">
        <button
          type="button"
          onClick={() => goToPage(0)}
          className={cn(
            'px-3 py-1 rounded-full text-xs font-medium transition-colors',
            activePage === 0
              ? 'bg-zinc-900/10 text-zinc-900 dark:bg-white/10 dark:text-white'
              : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white'
          )}
        >
          Chat
        </button>
        <button
          type="button"
          onClick={() => planTabEnabled && goToPage(1)}
          disabled={!planTabEnabled}
          className={cn(
            'px-3 py-1 rounded-full text-xs font-medium transition-colors relative',
            !planTabEnabled
              ? 'text-zinc-500 dark:text-zinc-400 opacity-50 cursor-not-allowed pointer-events-none'
              : activePage === 1
                ? 'bg-zinc-900/10 text-zinc-900 dark:bg-white/10 dark:text-white'
                : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white'
          )}
        >
          Plan
          {planTabEnabled && hasNewPlanContent && activePage !== 1 && (
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse ring-2 ring-white dark:ring-zinc-950" />
          )}
        </button>
      </div>

      {/* Horizontal scroll-snap container — height constrained by flex-1 + min-h-0.
          Each page is h-full with its own overflow-y so it scrolls independently
          rather than stretching to the tallest sibling (plan page). */}
      <div
        ref={containerRef}
        className="flex-1 flex overflow-x-auto overflow-y-hidden snap-x snap-mandatory no-scrollbar min-h-0 overscroll-x-contain webkit-momentum-scroll"
        onScroll={handleScroll}
      >
        {/* Page 0: Chat — h-full constrains to container, overflow-y-auto for independent scroll */}
        <div className="w-screen h-full shrink-0 snap-start overflow-y-auto touch-pan-y">
          {chatContent}
        </div>
        {/* Page 1: Plan — same pattern, scrolls independently */}
        <div className="w-screen h-full shrink-0 snap-start overflow-y-auto touch-pan-y">
          {planContent}
        </div>
      </div>
    </div>
  );
}

export const MobileSwipeLayout = memo(MobileSwipeLayoutInner);
