'use client';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

interface TimelineBlockListAddActivityButtonProps {
  dayNumber: number;
  date: string | null;
  disableFillDayActions: boolean;
  onBrowse: (dayNumber: number, date: string | null) => void;
}

export function TimelineBlockListAddActivityButton({
  dayNumber,
  date,
  disableFillDayActions,
  onBrowse,
}: TimelineBlockListAddActivityButtonProps) {
  return (
    <button
      type="button"
      onClick={() => onBrowse(dayNumber, date)}
      className={cn(
        'w-full min-h-[48px] rounded-xl border-2 border-dashed py-3 text-sm font-medium transition-all duration-200',
        'border-zinc-300 text-zinc-500 dark:border-white/15 dark:text-zinc-500',
        'hover:border-zinc-900 hover:text-zinc-900 dark:hover:border-emerald-500/30 dark:hover:text-emerald-400',
        `hover:${DS.glowClass.focusSm} active:scale-[0.98]`,
        disableFillDayActions && 'opacity-50 pointer-events-none cursor-not-allowed'
      )}
    >
      + Add activity
    </button>
  );
}
