'use client';

import { RefObject, useEffect, useRef, useState } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface UseScrollCollapseOptions {
  /** Scroll position threshold to trigger collapse (default: 100px) */
  threshold?: number;
  /** Buffer zone to prevent jitter at the threshold (default: 20px) */
  hysteresis?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * useScrollCollapse - Track scroll position to toggle collapsed state.
 *
 * Used for collapsing headers on scroll to maximize content visibility.
 * Implements hysteresis to prevent flickering at the threshold boundary.
 *
 * @param scrollRef - Ref to the scrollable container element
 * @param options - Configuration options
 * @returns isCollapsed - Whether the element should be in collapsed state
 *
 * @example
 * const scrollRef = useRef<HTMLDivElement>(null);
 * const isCollapsed = useScrollCollapse(scrollRef, { threshold: 60 });
 *
 * return (
 *   <div ref={scrollRef} className="overflow-y-auto">
 *     <Header isCollapsed={isCollapsed} />
 *     <Content />
 *   </div>
 * );
 */
export function useScrollCollapse(
  scrollRef: RefObject<HTMLElement | null>,
  options: UseScrollCollapseOptions = {}
): boolean {
  const { threshold = 100, hysteresis = 20 } = options;
  const [isCollapsed, setIsCollapsed] = useState(false);
  const isCollapsedRef = useRef(false);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;

    const handleScroll = () => {
      const scrollTop = element.scrollTop;

      // Collapse when scrolled past threshold + hysteresis
      if (!isCollapsedRef.current && scrollTop > threshold + hysteresis) {
        isCollapsedRef.current = true;
        setIsCollapsed(true);
      }
      // Expand when scrolled back above threshold
      else if (isCollapsedRef.current && scrollTop < threshold) {
        isCollapsedRef.current = false;
        setIsCollapsed(false);
      }
    };

    // Use passive listener for better scroll performance
    element.addEventListener('scroll', handleScroll, { passive: true });

    // Check initial scroll position
    handleScroll();

    return () => element.removeEventListener('scroll', handleScroll);
  }, [scrollRef, threshold, hysteresis]); // isCollapsed removed — ref handles it

  return isCollapsed;
}
