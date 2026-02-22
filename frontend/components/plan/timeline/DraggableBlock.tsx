'use client';

import { useDraggable } from '@dnd-kit/core';
import { Lock } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

interface DraggableBlockProps {
  block: DayBlock;
  dayNumber: number;
  children: ReactNode;
}

const LOCKED_TYPES = new Set(['arrival', 'departure', 'check-in', 'check-out', 'free_day']);

// These types render their own UI — skip the drag lock icon to avoid overlap or redundancy.
const NO_LOCK_ICON_TYPES = new Set(['arrival', 'departure', 'check-in', 'check-out', 'free_day']);

// Stable placeholder used when block.id is absent — keeps hook call order consistent.
const NO_ID_PLACEHOLDER = '__no_id__';

export function DraggableBlock({ block, dayNumber, children }: DraggableBlockProps) {
  const hasId = Boolean(block.id);
  const isLocked = !hasId || block.is_buffer || LOCKED_TYPES.has(block.activity_type);

  // Hooks must be called unconditionally — disabled when id is absent or block is locked
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: block.id ?? NO_ID_PLACEHOLDER,
    data: { block, dayNumber },
    disabled: isLocked,
  });

  // When no id, render a plain passthrough wrapper (no drag handle)
  if (!hasId) {
    return <>{children}</>;
  }

  return (
    <div
      ref={setNodeRef}
      {...(isLocked ? {} : { ...listeners, ...attributes })}
      className={cn(
        'relative transition-all duration-150',
        isLocked && 'cursor-not-allowed'
      )}
    >
      {isLocked && !NO_LOCK_ICON_TYPES.has(block.activity_type) && (
        <Lock className="absolute top-2 right-2 z-10 h-3 w-3 text-zinc-500 dark:text-zinc-400" />
      )}
      {isDragging ? (
        // Dashed "came from here" placeholder — fixed min-height approximates card
        <div
          className={cn(
            'rounded-xl border-2 border-dashed min-h-[4.5rem]',
            'border-zinc-300/50 dark:border-white/10',
            'bg-zinc-100/30 dark:bg-white/[0.02]',
          )}
        />
      ) : (
        children
      )}
    </div>
  );
}
