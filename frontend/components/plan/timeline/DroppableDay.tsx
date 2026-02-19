'use client';

import { useDndMonitor, useDroppable } from '@dnd-kit/core';
import { motion } from 'framer-motion';
import { useCallback, useMemo, useState } from 'react';

import { SPRING_CONFIG } from '@/lib/animation-config';
import { cn } from '@/lib/utils';

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
            'shadow-[inset_0_0_20px_-8px_rgba(16,185,129,0.15)]',
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
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ type: 'spring', ...SPRING_CONFIG.SLIDE }}
          />
        )}
      </div>
    </div>
  );
}
