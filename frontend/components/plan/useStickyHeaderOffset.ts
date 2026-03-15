'use client';

import { type RefObject,useLayoutEffect, useState } from 'react';

export function useStickyHeaderOffset(scrollContainerRef: RefObject<HTMLDivElement | null>): number {
  const [headerOffset, setHeaderOffset] = useState(0);

  useLayoutEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const measure = () => {
      const scrollRect = scrollContainer.getBoundingClientRect();
      setHeaderOffset(Math.round(scrollRect.top));
    };

    const observer = new ResizeObserver(measure);
    observer.observe(scrollContainer);
    measure();
    return () => observer.disconnect();
  }, [scrollContainerRef]);

  return headerOffset;
}
