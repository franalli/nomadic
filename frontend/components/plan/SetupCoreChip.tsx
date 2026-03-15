'use client';

import { type LucideIcon } from 'lucide-react';
import { memo } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

export interface SetupCoreChipProps {
  icon: LucideIcon;
  label: string;
  value?: string | null;
  onClick?: () => void;
  isOptional?: boolean;
  isDefault?: boolean;
  isMobile?: boolean;
  disabled?: boolean;
}

export const SetupCoreChip = memo(function SetupCoreChip({
  icon: Icon,
  label,
  value,
  onClick,
  isOptional,
  isDefault = false,
  isMobile = false,
  disabled = false,
}: SetupCoreChipProps) {
  const isSet = Boolean(value) && !isDefault;

  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-lg flex-shrink-0 cursor-pointer',
        isMobile ? 'h-10 px-4' : 'h-8 px-3',
        'transition-all duration-200 ease-out active:scale-[0.98]',
        'hover:scale-[1.02] hover:border-zinc-900 dark:hover:border-emerald-500/50',
        isSet && [
          'bg-zinc-50 border-2 border-zinc-900/30 text-zinc-900 font-semibold',
          'dark:bg-white/10 dark:text-white dark:border-emerald-500/30 dark:hover:bg-white/15',
        ],
        !isSet &&
          isOptional && [
            'bg-white border-2 border-dashed border-zinc-200 text-zinc-400',
            'dark:bg-white/5 dark:border-white/15 dark:text-zinc-500',
            'dark:hover:border-white/30 dark:hover:text-zinc-300',
          ],
        !isSet &&
          !isOptional && [
            'bg-white border-2 border-zinc-200 text-zinc-400',
            'dark:bg-white/5 dark:text-zinc-500 dark:border-white/15',
            'dark:hover:border-white/30 dark:hover:text-white',
          ],
        'focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-zinc-900/20 dark:focus-visible:ring-emerald-500/20',
        disabled && [
          'opacity-50 cursor-not-allowed pointer-events-none',
          'hover:scale-100 hover:border-current',
        ]
      )}
    >
      <Icon
        className={cn(
          'h-4 w-4 flex-shrink-0',
          isSet ? 'text-zinc-900 dark:text-emerald-400' : 'text-zinc-400 dark:text-zinc-500',
          disabled && 'opacity-50'
        )}
      />
      <span className="text-xs font-semibold uppercase tracking-wide whitespace-nowrap">
        {value || label}
        {!value && isOptional ? (
          <span
            className={`${DS.textSize.micro} opacity-50 ml-1 normal-case tracking-normal`}
          >
            (opt)
          </span>
        ) : null}
      </span>
    </button>
  );
});
