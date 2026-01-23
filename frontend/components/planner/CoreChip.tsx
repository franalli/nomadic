/**
 * CoreChip
 *
 * Presentational-only chip component for trip constraints.
 * Strict contract: no store imports, no formatting logic, no phase knowledge.
 *
 * Used by:
 * - TripSummaryPills (header pills in Plan mode)
 * - UnifiedChipRow (left panel chips in Setup mode)
 */

'use client';

import { Check } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';

export interface CoreChipProps {
  icon: LucideIcon;
  label: string;              // "Dates"
  value?: string | null;      // "Dec 15-22" (pre-formatted)
  placeholder?: string;       // "Add dates" (shown when no value)
  onClick?: () => void;
  tone?: 'default' | 'missing' | 'optional';
  disabled?: boolean;         // Disable during streaming/loading
  /** Use 'onImage' when chip is on a hero/photo background */
  variant?: 'default' | 'onImage';
}

export const CoreChip = memo(function CoreChip({
  icon: Icon,
  label,
  value,
  placeholder,
  onClick,
  tone = 'default',
  disabled = false,
  variant = 'default',
}: CoreChipProps) {
  const hasValue = !!value;
  const displayText = value || placeholder || label;
  const isOnImage = variant === 'onImage';

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        // Mobile scrolling support
        'snap-start shrink-0',
        // Base styling (h-7 = 28px)
        'inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border',
        'transition-all duration-[120ms] ease-out active:scale-[0.98]',
        // Disabled state
        disabled && 'opacity-50 pointer-events-none',

        // === ON-IMAGE VARIANT (for hero/photo backgrounds) ===
        // Use WHITE backgrounds for visibility on any photo - colored borders/text indicate state
        isOnImage && hasValue && 'border-emerald-600/60 bg-white/90 text-emerald-800 backdrop-blur-md shadow-sm font-semibold dark:border-emerald-400/50 dark:bg-black/50 dark:text-emerald-300',
        isOnImage && !hasValue && tone === 'missing' && 'border-amber-600/60 border-dashed bg-white/85 text-amber-800 backdrop-blur-md shadow-sm dark:border-amber-400/50 dark:bg-black/40 dark:text-amber-300',
        isOnImage && !hasValue && tone === 'optional' && 'border-slate-400/40 bg-white/75 text-slate-600 backdrop-blur-md shadow-sm dark:border-white/20 dark:bg-black/35 dark:text-white/70',
        isOnImage && !hasValue && tone === 'default' && 'border-slate-400/50 bg-white/85 text-slate-700 backdrop-blur-md shadow-sm dark:border-white/25 dark:bg-black/40 dark:text-white/85',
        // Hover for onImage
        isOnImage && !disabled && 'hover:bg-white/95 dark:hover:bg-black/55',

        // === DEFAULT VARIANT (for normal page backgrounds) ===
        !isOnImage && hasValue && 'border-[var(--chip-active-border)] bg-[var(--chip-active-bg)] text-[var(--chip-active-text)] font-semibold',
        !isOnImage && !hasValue && tone === 'missing' && 'border-dashed border-amber-500/50 bg-amber-500/5 text-amber-400',
        !isOnImage && !hasValue && tone === 'optional' && 'border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)] opacity-70',
        !isOnImage && !hasValue && tone === 'default' && 'border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)]',
        // Hover for default
        !isOnImage && !disabled && !hasValue && 'hover:border-[var(--chip-border-hover)]',
        !isOnImage && !disabled && hasValue && 'hover:border-[var(--chip-active-border)]',

        // Focus ring
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--chip-active-icon)]/50'
      )}
    >
      <Icon
        className={cn(
          'h-3.5 w-3.5 flex-shrink-0',
          // Icon color based on variant and state
          isOnImage && hasValue && 'text-emerald-600 dark:text-emerald-400',
          isOnImage && !hasValue && tone === 'missing' && 'text-amber-600 dark:text-amber-400',
          isOnImage && !hasValue && tone !== 'missing' && 'text-slate-500 dark:text-white/60',
          !isOnImage && hasValue && 'text-[var(--chip-active-icon)]'
        )}
      />
      <span className="text-xs truncate max-w-[120px]">{displayText}</span>
      {hasValue && (
        <Check
          className={cn(
            'h-2.5 w-2.5',
            isOnImage ? 'text-emerald-700 dark:text-emerald-400' : 'text-[var(--chip-active-icon)]'
          )}
        />
      )}
    </button>
  );
});

export default CoreChip;
