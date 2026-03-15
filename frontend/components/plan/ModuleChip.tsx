'use client';

import { Check, type LucideIcon } from 'lucide-react';
import { memo } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

export type ModuleState = 'off' | 'on-default' | 'on-custom';

export interface ModuleChipProps {
  icon: LucideIcon;
  label: string;
  state: ModuleState;
  summary?: string | null;
  onClick?: () => void;
  isMobile?: boolean;
  disabled?: boolean;
  badge?: number;
  showCompletionCheckWhenOn?: boolean;
}

export const ModuleChip = memo(function ModuleChip({
  icon: Icon,
  label,
  state,
  summary,
  onClick,
  isMobile = false,
  disabled = false,
  badge,
  showCompletionCheckWhenOn = true,
}: ModuleChipProps) {
  const isOn = state === 'on-default' || state === 'on-custom';
  const showCompletionCheck = isOn && showCompletionCheckWhenOn;

  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={cn(
        'relative inline-flex items-center gap-1.5 rounded-full flex-shrink-0',
        isMobile ? 'h-11 px-5' : 'h-9 px-4',
        'transition-all duration-200 ease-out active:scale-[0.95]',
        !isOn && [
          'bg-white border-2 border-zinc-200 text-zinc-400 hover:border-zinc-900 hover:text-zinc-600',
          'dark:bg-white/5 dark:border-white/15 dark:text-zinc-500',
          'dark:hover:border-white/30 dark:hover:text-zinc-300',
        ],
        isOn && [
          'bg-zinc-900 text-white border-2 border-transparent font-medium hover:bg-zinc-800',
          'dark:bg-white dark:text-black dark:border-transparent dark:hover:bg-zinc-100',
        ],
        'focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-zinc-900/20 dark:focus-visible:ring-emerald-500/30',
        disabled && 'opacity-50 cursor-not-allowed pointer-events-none'
      )}
    >
      {showCompletionCheck ? (
        <Check className="h-4 w-4 flex-shrink-0 text-current" strokeWidth={2.5} />
      ) : (
        <Icon
          className={cn(
            'h-4 w-4 flex-shrink-0',
            isOn ? 'text-current' : 'text-zinc-400 dark:text-zinc-500'
          )}
        />
      )}
      <span className="text-sm">
        {label}
        {isOn && summary ? <span className="ml-1.5 text-xs opacity-75">· {summary}</span> : null}
      </span>
      {badge != null && badge > 0 ? (
        <span
          className={cn(
            'absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full',
            'bg-emerald-500 text-white flex items-center justify-center shadow-sm',
            `${DS.textSize.micro} font-bold`
          )}
        >
          {badge}
        </span>
      ) : null}
    </button>
  );
});
