'use client';

/**
 * useChatScrolling — scroll management for ChatPanel.
 *
 * Owns refs and functions for smooth-scrolling the chat message container,
 * tracking whether the user has scrolled up, and collapsing the mobile
 * setup header on scroll.
 */

import { useCallback, useEffect, useMemo, useRef } from 'react';

export interface ChatScrollingResult {
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  bottomSentinelRef: React.RefObject<HTMLDivElement | null>;
  scrollToBottom: (force?: boolean) => void;
  handleScroll: () => void;
  scrollPanelIntoView: () => void;
  isUserScrolledUp: () => boolean;
  /** Exposed for cleanup in ChatPanel (timeout refs) */
  scrollTimeoutRef: React.MutableRefObject<NodeJS.Timeout | null>;
}

interface UseChatScrollingParams {
  panelRef: React.RefObject<HTMLDivElement | null>;
  isDesktop: boolean;
  onSetupHeaderCollapse: (collapsed: boolean) => void;
}

const PROGRAMMATIC_SCROLL_WINDOW_MS = 40;
const FORCE_SETTLE_CHECK_INTERVAL_MS = 80;
const FORCE_SETTLE_MAX_DURATION_MS = 1200;

function findScrollableAncestor(node: HTMLElement | null): HTMLElement | null {
  let current = node?.parentElement ?? null;

  while (current) {
    const { overflowY } = window.getComputedStyle(current);
    if (overflowY === 'auto' || overflowY === 'scroll') {
      return current;
    }
    current = current.parentElement;
  }

  return null;
}

export function useChatScrolling({
  panelRef,
  isDesktop,
  onSetupHeaderCollapse,
}: UseChatScrollingParams): ChatScrollingResult {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const bottomSentinelRef = useRef<HTMLDivElement | null>(null);
  const isUserScrolledUpRef = useRef(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const scrollAnimationFrameRef = useRef<number | null>(null);
  const forceSettleTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const forceSettleDeadlineRef = useRef(0);
  const plannerRailSettleTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const plannerRailSettleDeadlineRef = useRef(0);
  const plannerRailElementRef = useRef<HTMLElement | null>(null);
  const plannerRailScrollListenerRef = useRef<(() => void) | null>(null);
  const lastKnownPlannerRailScrollTopRef = useRef(0);
  const programmaticScrollUntilRef = useRef(0);
  const lastKnownScrollTopRef = useRef(0);

  // Check if user is near the bottom of the scroll container
  const isNearBottom = useCallback(() => {
    const node = scrollContainerRef.current;
    if (!node) return true;
    const threshold = 100; // pixels from bottom to consider "at bottom"
    return node.scrollHeight - node.scrollTop - node.clientHeight < threshold;
  }, []);

  const clearForceSettleTimeout = useCallback(() => {
    if (forceSettleTimeoutRef.current) {
      clearTimeout(forceSettleTimeoutRef.current);
      forceSettleTimeoutRef.current = null;
    }
    forceSettleDeadlineRef.current = 0;
  }, []);

  const detachPlannerRailListener = useCallback(() => {
    if (plannerRailElementRef.current && plannerRailScrollListenerRef.current) {
      plannerRailElementRef.current.removeEventListener(
        'scroll',
        plannerRailScrollListenerRef.current
      );
      plannerRailElementRef.current = null;
    }
    plannerRailScrollListenerRef.current = null;
    lastKnownPlannerRailScrollTopRef.current = 0;
  }, []);

  const clearPlannerRailSettleTimeout = useCallback(() => {
    if (plannerRailSettleTimeoutRef.current) {
      clearTimeout(plannerRailSettleTimeoutRef.current);
      plannerRailSettleTimeoutRef.current = null;
    }
    plannerRailSettleDeadlineRef.current = 0;
    detachPlannerRailListener();
  }, [detachPlannerRailListener]);

  const attachPlannerRailListener = useCallback((rail: HTMLElement) => {
    if (plannerRailElementRef.current === rail) return;

    detachPlannerRailListener();

    const listener = () => {
      const currentScrollTop = rail.scrollTop;
      const distanceToBottom = Math.max(
        rail.scrollHeight - currentScrollTop - rail.clientHeight,
        0
      );
      const userScrolledUp =
        currentScrollTop < lastKnownPlannerRailScrollTopRef.current - 1 &&
        distanceToBottom > 1;

      if (userScrolledUp) {
        if (plannerRailSettleTimeoutRef.current) {
          clearTimeout(plannerRailSettleTimeoutRef.current);
          plannerRailSettleTimeoutRef.current = null;
        }
        plannerRailSettleDeadlineRef.current = 0;
        detachPlannerRailListener();
        return;
      }

      lastKnownPlannerRailScrollTopRef.current = currentScrollTop;
    };

    plannerRailElementRef.current = rail;
    plannerRailScrollListenerRef.current = listener;
    rail.addEventListener('scroll', listener, { passive: true });
    lastKnownPlannerRailScrollTopRef.current = rail.scrollTop;
  }, [detachPlannerRailListener]);

  const markProgrammaticScroll = useCallback(() => {
    programmaticScrollUntilRef.current =
      performance.now() + PROGRAMMATIC_SCROLL_WINDOW_MS;
  }, []);

  const isProgrammaticScrollActive = useCallback(
    () => performance.now() <= programmaticScrollUntilRef.current,
    []
  );

  // Custom smooth scroll with controlled duration
  const smoothScrollTo = useCallback(
    (element: HTMLElement, targetScrollTop: number, duration: number) => {
      const startScrollTop = element.scrollTop;
      const distance = targetScrollTop - startScrollTop;
      const startTime = performance.now();

      // Ease-out cubic for natural deceleration
      const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

      const animateScroll = (currentTime: number) => {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const easedProgress = easeOutCubic(progress);

        markProgrammaticScroll();
        element.scrollTop = startScrollTop + distance * easedProgress;
        lastKnownScrollTopRef.current = element.scrollTop;

        if (progress < 1) {
          scrollAnimationFrameRef.current = requestAnimationFrame(animateScroll);
        } else {
          scrollAnimationFrameRef.current = null;
        }
      };

      scrollAnimationFrameRef.current = requestAnimationFrame(animateScroll);
    },
    [markProgrammaticScroll]
  );

  const cancelPendingScrollWork = useCallback(() => {
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
      scrollTimeoutRef.current = null;
    }
    if (scrollAnimationFrameRef.current !== null) {
      cancelAnimationFrame(scrollAnimationFrameRef.current);
      scrollAnimationFrameRef.current = null;
    }
    clearForceSettleTimeout();
  }, [clearForceSettleTimeout]);

  const snapToBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    markProgrammaticScroll();
    container.scrollTop = Math.max(container.scrollHeight - container.clientHeight, 0);
    lastKnownScrollTopRef.current = container.scrollTop;
  }, [markProgrammaticScroll]);

  const scheduleForceSettle = useCallback(() => {
    clearForceSettleTimeout();
    forceSettleDeadlineRef.current = performance.now() + FORCE_SETTLE_MAX_DURATION_MS;

    const runSettlePass = () => {
      const container = scrollContainerRef.current;
      if (!container) {
        clearForceSettleTimeout();
        return;
      }

      const targetScrollTop = Math.max(container.scrollHeight - container.clientHeight, 0);
      const distanceToBottom = Math.abs(container.scrollTop - targetScrollTop);

      if (distanceToBottom > 1) {
        snapToBottom();
      }

      if (performance.now() >= forceSettleDeadlineRef.current) {
        clearForceSettleTimeout();
        return;
      }

      forceSettleTimeoutRef.current = setTimeout(() => {
        forceSettleTimeoutRef.current = null;
        runSettlePass();
      }, FORCE_SETTLE_CHECK_INTERVAL_MS);
    };

    runSettlePass();
  }, [clearForceSettleTimeout, snapToBottom]);

  // Smooth scroll to bottom using custom animation
  const scrollToBottom = useCallback(
    (force = false) => {
      // Don't auto-scroll if user has scrolled up, unless forced
      if (!force && isUserScrolledUpRef.current) return;

      // Reset scroll-up tracking on force so subsequent soft scrolls also work
      if (force) {
        isUserScrolledUpRef.current = false;
      }

      const container = scrollContainerRef.current;
      if (!container) return;

      cancelPendingScrollWork();

      scrollTimeoutRef.current = setTimeout(() => {
        scrollTimeoutRef.current = null;

        if (force) {
          snapToBottom();
          scheduleForceSettle();
          return;
        }

        const targetScrollTop = container.scrollHeight - container.clientHeight;
        // 2000ms duration for a slow, relaxed scroll
        smoothScrollTo(container, targetScrollTop, 2000);
      }, 16); // Single frame delay for batching
    },
    [cancelPendingScrollWork, scheduleForceSettle, smoothScrollTo, snapToBottom]
  );

  // Track user scroll position to avoid fighting user scroll
  // Also track scroll position for mobile setup header collapse (threshold: 50px)
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const currentScrollTop = container.scrollTop;
    const distanceToBottom =
      Math.max(container.scrollHeight - currentScrollTop - container.clientHeight, 0);
    const userScrolledUpManually =
      currentScrollTop < lastKnownScrollTopRef.current - 1 &&
      distanceToBottom > 1;
    const userScrolledUp = !isNearBottom();
    isUserScrolledUpRef.current = userScrolledUpManually || userScrolledUp;

    if (userScrolledUpManually || (userScrolledUp && !isProgrammaticScrollActive())) {
      cancelPendingScrollWork();
    }

    // Mobile setup header collapse: collapse when scrolled past 50px
    if (!isDesktop) {
      const shouldCollapse = container.scrollTop > 50;
      onSetupHeaderCollapse(shouldCollapse);
    }

    lastKnownScrollTopRef.current = currentScrollTop;
  }, [
    cancelPendingScrollWork,
    isNearBottom,
    isDesktop,
    isProgrammaticScrollActive,
    onSetupHeaderCollapse,
  ]);

  const scrollPlannerRailToBottom = useCallback((behavior: ScrollBehavior) => {
    if (!isDesktop) return false;

    const panel = panelRef.current;
    if (!panel) return false;

    const scrollParent = findScrollableAncestor(panel);
    if (!scrollParent) return false;

    attachPlannerRailListener(scrollParent);
    const targetTop = Math.max(scrollParent.scrollHeight - scrollParent.clientHeight, 0);
    if (typeof scrollParent.scrollTo === 'function') {
      scrollParent.scrollTo({ top: targetTop, behavior });
    } else {
      scrollParent.scrollTop = targetTop;
    }
    lastKnownPlannerRailScrollTopRef.current = targetTop;
    return true;
  }, [attachPlannerRailListener, isDesktop, panelRef]);

  const schedulePlannerRailSettle = useCallback(() => {
    if (!isDesktop) return false;

    clearPlannerRailSettleTimeout();
    plannerRailSettleDeadlineRef.current = performance.now() + FORCE_SETTLE_MAX_DURATION_MS;

    const runSettlePass = (behavior: ScrollBehavior) => {
      if (!scrollPlannerRailToBottom(behavior)) {
        clearPlannerRailSettleTimeout();
        return;
      }

      if (performance.now() >= plannerRailSettleDeadlineRef.current) {
        clearPlannerRailSettleTimeout();
        return;
      }

      plannerRailSettleTimeoutRef.current = setTimeout(() => {
        plannerRailSettleTimeoutRef.current = null;
        runSettlePass('auto');
      }, FORCE_SETTLE_CHECK_INTERVAL_MS);
    };

    runSettlePass('smooth');
    return true;
  }, [clearPlannerRailSettleTimeout, isDesktop, scrollPlannerRailToBottom]);

  // Scroll the desktop planner rail (or fallback element) to keep the chat footer visible.
  const scrollPanelIntoView = useCallback(() => {
    requestAnimationFrame(() => {
      if (schedulePlannerRailSettle()) return;
      panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    });
  }, [panelRef, schedulePlannerRailSettle]);

  // Cleanup scroll timeout on unmount
  useEffect(() => {
    return () => {
      cancelPendingScrollWork();
      clearPlannerRailSettleTimeout();
    };
  }, [cancelPendingScrollWork, clearPlannerRailSettleTimeout]);

  const isUserScrolledUp = useCallback(() => isUserScrolledUpRef.current, []);

  return useMemo(
    () => ({
      scrollContainerRef,
      bottomSentinelRef,
      scrollToBottom,
      handleScroll,
      scrollPanelIntoView,
      isUserScrolledUp,
      scrollTimeoutRef,
    }),
    [scrollToBottom, handleScroll, scrollPanelIntoView, isUserScrolledUp]
  );
}
