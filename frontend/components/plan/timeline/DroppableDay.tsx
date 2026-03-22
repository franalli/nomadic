'use client';

import { useDndMonitor, useDroppable } from '@dnd-kit/core';
import { motion } from 'framer-motion';
import { useCallback, useMemo, useState } from 'react';

import { SPRING_CONFIG } from '@/lib/animation-config';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

// Animation constants (hoisted to avoid new object refs per render)
const DROP_INDICATOR_INITIAL = { scaleX: 0 };
const DROP_INDICATOR_ANIMATE = { scaleX: 1 };
const DROP_INDICATOR_TRANSITION = { type: 'spring' as const, ...SPRING_CONFIG.SLIDE };

interface DroppableDayProps {
  dayNumber: number;
  children: React.ReactNode;
}

export function DroppableDay({ dayNumber, children }: DroppableDayProps) {
  const { isOver, setNodeRef } = useDroppable({ id: `day-${dayNumber}` });
  const [isDragActive, setIsDragActive] = useState(false);

  const setActive = useCallback(() => setIsDragActive(true), []);
  const setInactive = useCallback(() => setIsDragActive(false), []);
  useDndMonitor(
    useMemo(() => ({ onDragStart: setActive, onDragEnd: setInactive, onDragCancel: setInactive }), [setActive, setInactive])
  );

  return (
    // Outer div: full hit area for collision detection (min-h ensures empty days are droppable)
    <div ref={setNodeRef} className="min-h-[80px]">
      {/* Inner div: ring + highlight, sized tightly to content */}
      <div
        className={cn(
          'rounded-xl transition-all duration-200',
          isOver && [
            'ring-1 ring-emerald-500/25 dark:ring-emerald-500/20',
            'bg-emerald-500/[0.04] dark:bg-emerald-500/[0.03]',
            DS.shadow.dropTargetInset,
          ],
          !isOver && isDragActive && [
            'ring-1 ring-zinc-300/50 dark:ring-white/10',
          ],
        )}
      >
        {children}
        {isOver && (
          <motion.div
            layoutId="drop-indicator"
            className="h-0.5 bg-emerald-500 rounded-full mx-4 my-1"
            initial={DROP_INDICATOR_INITIAL}
            animate={DROP_INDICATOR_ANIMATE}
            transition={DROP_INDICATOR_TRANSITION}
          />
        )}
      </div>
    </div>
  );
}
