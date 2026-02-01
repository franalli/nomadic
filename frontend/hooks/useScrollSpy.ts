import { useCallback,useEffect, useState } from 'react';

/**
 * useScrollSpy
 *
 * Intersection observer hook for scroll-based map synchronization.
 * Detects which timeline item is currently in the viewport center
 * and returns its ID for map flyTo animation.
 *
 * @param itemIds - Array of item IDs to observe
 * @param containerRef - Optional ref to the scrollable container (defaults to viewport)
 * @returns Active item ID or null
 */
export function useScrollSpy(
  itemIds: string[],
  containerRef?: React.RefObject<HTMLElement | null>
): string | null {
  const [activeId, setActiveId] = useState<string | null>(null);

  const handleIntersection = useCallback((entries: IntersectionObserverEntry[]) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const mapId = entry.target.getAttribute('data-map-id');
        if (mapId) {
          setActiveId(mapId);
        }
      }
    });
  }, []);

  useEffect(() => {
    // Skip if no items to observe
    if (itemIds.length === 0) return;

    const observer = new IntersectionObserver(handleIntersection, {
      root: containerRef?.current ?? null,
      // Trigger when item is in the middle 20% of the viewport
      rootMargin: '-40% 0px -40% 0px',
      threshold: 0.5,
    });

    // Observe all timeline items
    itemIds.forEach((id) => {
      const element = document.getElementById(`timeline-item-${id}`);
      if (element) {
        observer.observe(element);
      }
    });

    return () => {
      observer.disconnect();
    };
  }, [itemIds, containerRef, handleIntersection]);

  return activeId;
}
