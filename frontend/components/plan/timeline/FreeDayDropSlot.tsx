'use client';

import { useDndMonitor, useDroppable } from '@dnd-kit/core';
import { motion } from 'framer-motion';
import { useCallback, useMemo, useState } from 'react';

import { SPRING_CONFIG } from '@/lib/animation-config';
import { cn } from '@/lib/utils';

// Animation constants (hoisted to avoid new object refs per render)
const DROP_INDICATOR_INITIAL = { scaleX: 0 };
const DROP_INDICATOR_ANIMATE = { scaleX: 1 };
const DROP_INDICATOR_TRANSITION = { type: 'spring' as const, ...SPRING_CONFIG.SLIDE };

interface FreeDayDropSlotProps {
  dayNumber: number;
}

/**
 * Dedicated drop target for FreeDayCard (empty day state).
 * Uses the same droppable ID scheme as DroppableDay (`day-${dayNumber}`)
 * so drops register identically in ItineraryDndWrapper.
 *
 * Rendered inside FreeDayCard between the subtitle and specialist chips.
 * Only visible when a drag is in progress.
 */
export function FreeDayDropSlot({ dayNumber }: FreeDayDropSlotProps) {
  // Uses 'free-day-' prefix (not 'day-') to avoid duplicate droppable ID conflicts
  // with DroppableDay on activity days. ItineraryDndWrapper normalises both prefixes.
  const { isOver, setNodeRef } = useDroppable({ id: `free-day-${dayNumber}` });
  const [isDragActive, setIsDragActive] = useState(false);

  const setActive = useCallback(() => setIsDragActive(true), []);
  const setInactive = useCallback(() => setIsDragActive(false), []);
  useDndMonitor(
    useMemo(
      () => ({ onDragStart: setActive, onDragEnd: setInactive, onDragCancel: setInactive }),
      [setActive, setInactive]
    )
  );

  // Hidden when no drag is active — takes no space
  if (!isDragActive) return null;

  return (
    <div
      ref={setNodeRef}
      className={cn(
        'mb-4 rounded-lg border-2 border-dashed transition-all duration-200 flex items-center justify-center h-10',
        isOver
          ? [
              'border-emerald-500/50 dark:border-emerald-500/40',
              'bg-emerald-500/[0.06] dark:bg-emerald-500/[0.04]',
            ]
          : [
              'border-zinc-300/60 dark:border-white/10',
              'bg-zinc-100/20 dark:bg-white/[0.01]',
            ]
      )}
    >
      {isOver ? (
        <motion.div
          className="h-0.5 bg-emerald-500 rounded-full w-16"
          initial={DROP_INDICATOR_INITIAL}
          animate={DROP_INDICATOR_ANIMATE}
          transition={DROP_INDICATOR_TRANSITION}
        />
      ) : (
        <span className="text-xs text-zinc-400 dark:text-zinc-600 select-none">
          Drop here
        </span>
      )}
    </div>
  );
}
