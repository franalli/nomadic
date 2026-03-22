'use client';

/**
 * DestinationSheetParts — Extracted sub-components for DestinationSheet.
 */

import { MapPin } from 'lucide-react';

import { cn } from '@/lib/utils';

interface DestinationPillProps {
  label: string;
  onClick: () => void;
}

const pillClasses = cn(
  'inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-lg',
  // Tactile Rule: border-2 for visibility, snap-to-black on hover
  'bg-white border-2 border-zinc-200',
  'text-xs font-semibold text-zinc-600',
  'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
  // Dark: Glass Fill with border-2
  'dark:bg-white/5 dark:border-2 dark:border-white/15',
  'dark:text-zinc-400',
  'dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white',
  'transition-all duration-150'
);

/** Reusable destination pill button used for both Recent and Popular sections. */
export function DestinationPill({ label, onClick }: DestinationPillProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={pillClasses}
    >
      <MapPin className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
