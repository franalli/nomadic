'use client';

import { useCallback, useEffect, useRef } from 'react';

import { useMapSync } from '@/hooks/useMapSync';
import { useUIStore } from '@/state/uiStore';

import type { TimelineVariant } from './TimelineThread';

export function useTimelineThreadMapSync(
  sortedDayNumbers: number[],
  effectiveVariant: TimelineVariant
): (dayNumber: number, el: HTMLElement | null) => void {
  const dayHeaderRefs = useRef<Map<number, HTMLElement>>(new Map());
  const scrollContainerRef = useRef<HTMLElement | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollTarget = useMapSync((s) => s.scrollTargetDayNumber);
  const clearScrollTarget = useMapSync((s) => s.clearScrollTarget);

  const dayHeaderRef = useCallback((dayNumber: number, el: HTMLElement | null) => {
    if (el) {
      dayHeaderRefs.current.set(dayNumber, el);
    } else {
      dayHeaderRefs.current.delete(dayNumber);
    }
  }, []);

  const debouncedSetDay = useCallback((day: number) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      useMapSync.getState().setVisibleDayNumber(day);
    }, 150);
  }, []);

  useEffect(() => {
    let prevId: string | null = null;
    const unsub = useUIStore.subscribe((state) => {
      const id = state.hoveredActivityId;
      if (id === prevId) return;
      if (prevId) {
        document.getElementById(`timeline-item-${prevId}`)?.removeAttribute('data-map-hovered');
      }
      if (id) {
        document.getElementById(`timeline-item-${id}`)?.setAttribute('data-map-hovered', 'true');
      }
      prevId = id;
    });
    return unsub;
  }, []);

  useEffect(() => {
    if (effectiveVariant !== 'real') return;

    let firstHeader: HTMLElement | undefined;
    for (const value of dayHeaderRefs.current.values()) {
      firstHeader = value;
      break;
    }

    if (firstHeader) {
      let el: HTMLElement | null = firstHeader.parentElement;
      while (el) {
        const overflow = window.getComputedStyle(el).overflowY;
        if (overflow === 'auto' || overflow === 'scroll') {
          scrollContainerRef.current = el;
          break;
        }
        el = el.parentElement;
      }
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);

        if (visible.length > 0) {
          const dayNumber = parseInt(visible[0].target.getAttribute('data-day') ?? '0', 10);
          if (dayNumber > 0) {
            debouncedSetDay(dayNumber);
          }
        }
      },
      {
        root: scrollContainerRef.current ?? null,
        rootMargin: '-30% 0px -30% 0px',
        threshold: [0, 0.25, 0.5, 0.75, 1],
      }
    );

    dayHeaderRefs.current.forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [debouncedSetDay, effectiveVariant, sortedDayNumbers]);

  useEffect(() => {
    if (scrollTarget === null || effectiveVariant !== 'real') return;

    const dayEl = dayHeaderRefs.current.get(scrollTarget);
    if (dayEl) {
      dayEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    clearScrollTarget();
  }, [clearScrollTarget, effectiveVariant, scrollTarget]);

  return dayHeaderRef;
}
