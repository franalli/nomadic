'use client';

import { type RefObject,useCallback, useEffect, useState } from 'react';

export function useTripSummaryFade(
  scrollRef: RefObject<HTMLDivElement | null>
): boolean {
  const [showRightFade, setShowRightFade] = useState(false);

  const updateFadeState = useCallback(() => {
    const element = scrollRef.current;
    if (!element) {
      setShowRightFade(false);
      return;
    }

    const hasOverflow = element.scrollWidth - element.clientWidth > 4;
    const atEnd = element.scrollLeft + element.clientWidth >= element.scrollWidth - 4;
    setShowRightFade(hasOverflow && !atEnd);
  }, [scrollRef]);

  useEffect(() => {
    updateFadeState();
    const element = scrollRef.current;
    if (!element) return;

    const handleScroll = () => updateFadeState();
    element.addEventListener('scroll', handleScroll, { passive: true });

    const resizeObserver =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => updateFadeState());
    resizeObserver?.observe(element);
    if (element.firstElementChild instanceof HTMLElement) {
      resizeObserver?.observe(element.firstElementChild);
    }

    window.addEventListener('resize', updateFadeState);
    return () => {
      element.removeEventListener('scroll', handleScroll);
      resizeObserver?.disconnect();
      window.removeEventListener('resize', updateFadeState);
    };
  }, [scrollRef, updateFadeState]);

  return showRightFade;
}
