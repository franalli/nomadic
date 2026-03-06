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

export function useChatScrolling({
  panelRef,
  isDesktop,
  onSetupHeaderCollapse,
}: UseChatScrollingParams): ChatScrollingResult {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const bottomSentinelRef = useRef<HTMLDivElement | null>(null);
  const isUserScrolledUpRef = useRef(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Check if user is near the bottom of the scroll container
  const isNearBottom = useCallback(() => {
    const node = scrollContainerRef.current;
    if (!node) return true;
    const threshold = 100; // pixels from bottom to consider "at bottom"
    return node.scrollHeight - node.scrollTop - node.clientHeight < threshold;
  }, []);

  // Custom smooth scroll with controlled duration
  const smoothScrollTo = useCallback((element: HTMLElement, targetScrollTop: number, duration: number) => {
    const startScrollTop = element.scrollTop;
    const distance = targetScrollTop - startScrollTop;
    const startTime = performance.now();

    // Ease-out cubic for natural deceleration
    const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

    const animateScroll = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easeOutCubic(progress);

      element.scrollTop = startScrollTop + distance * easedProgress;

      if (progress < 1) {
        requestAnimationFrame(animateScroll);
      }
    };

    requestAnimationFrame(animateScroll);
  }, []);

  // Smooth scroll to bottom using custom animation
  const scrollToBottom = useCallback((force = false) => {
    // Don't auto-scroll if user has scrolled up, unless forced
    if (!force && isUserScrolledUpRef.current) return;

    // Reset scroll-up tracking on force so subsequent soft scrolls also work
    if (force) {
      isUserScrolledUpRef.current = false;
    }

    const container = scrollContainerRef.current;
    if (!container) return;

    // Debounce rapid scroll calls to prevent jitter
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }

    scrollTimeoutRef.current = setTimeout(() => {
      const targetScrollTop = container.scrollHeight - container.clientHeight;
      // 2000ms duration for a slow, relaxed scroll
      smoothScrollTo(container, targetScrollTop, 2000);
    }, 16); // Single frame delay for batching
  }, [smoothScrollTo]);

  // Track user scroll position to avoid fighting user scroll
  // Also track scroll position for mobile setup header collapse (threshold: 50px)
  const handleScroll = useCallback(() => {
    isUserScrolledUpRef.current = !isNearBottom();

    // Mobile setup header collapse: collapse when scrolled past 50px
    const container = scrollContainerRef.current;
    if (container && !isDesktop) {
      const shouldCollapse = container.scrollTop > 50;
      onSetupHeaderCollapse(shouldCollapse);
    }
  }, [isNearBottom, isDesktop, onSetupHeaderCollapse]);

  // Scroll the page to bring chat panel into view (used after send/receive)
  const scrollPanelIntoView = useCallback(() => {
    requestAnimationFrame(() => {
      panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    });
  }, [panelRef]);

  // Cleanup scroll timeout on unmount
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
    };
  }, []);

  const isUserScrolledUp = useCallback(() => isUserScrolledUpRef.current, []);

  return useMemo(() => ({
    scrollContainerRef,
    bottomSentinelRef,
    scrollToBottom,
    handleScroll,
    scrollPanelIntoView,
    isUserScrolledUp,
    scrollTimeoutRef,
  }), [scrollToBottom, handleScroll, scrollPanelIntoView, isUserScrolledUp]);
}
