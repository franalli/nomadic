'use client';

/**
 * ChipScrollContainer
 *
 * Horizontal scroll wrapper for chip rows.
 * Applies mobile scroll bleed pattern (overflow-x-auto, no-scrollbar, -mx-4 px-4)
 * or desktop centered layout based on the `scroll` prop.
 */

import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface ChipScrollContainerProps {
  children: ReactNode;
  /** When true, applies horizontal scroll + bleed pattern (mobile). */
  scroll?: boolean;
  /** Additional className overrides. */
  className?: string;
}

export function ChipScrollContainer({
  children,
  scroll = false,
  className,
}: ChipScrollContainerProps) {
  return (
    <div
      className={cn(
        'flex items-center',
        scroll
          ? 'gap-1.5 overflow-x-auto no-scrollbar -mx-4 px-4 py-1'
          : 'gap-1.5 flex-nowrap justify-center',
        className
      )}
    >
      {children}
    </div>
  );
}

export default ChipScrollContainer;
