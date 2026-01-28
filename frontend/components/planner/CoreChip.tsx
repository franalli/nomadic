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

import type { LucideIcon } from 'lucide-react';
import { Check } from 'lucide-react';
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
        // Flexible sizing
        'snap-start min-w-0',
        // Base styling (h-6 = 24px on mobile for compact fit)
        'inline-flex items-center gap-1 h-6 px-2 rounded-full border text-[11px]',
        'transition-all duration-[120ms] ease-out active:scale-[0.98]',
        // Disabled state
        disabled && 'opacity-50 pointer-events-none',

        // === ON-IMAGE VARIANT (for hero/photo backgrounds) ===
        // FROSTED GLASS: Dark semi-transparent base with blur - lets photo colors bleed through
        isOnImage && hasValue && 'border-white/20 bg-black/20 backdrop-blur-md text-white font-semibold shadow-sm',
        isOnImage && !hasValue && tone === 'missing' && 'border-amber-400/40 border-dashed bg-black/15 backdrop-blur-md text-white/90 shadow-sm',
        isOnImage && !hasValue && tone === 'optional' && 'border-white/15 bg-black/10 backdrop-blur-md text-white/70 shadow-sm',
        isOnImage && !hasValue && tone === 'default' && 'border-white/20 bg-black/15 backdrop-blur-md text-white/85 shadow-sm',
        // Hover for onImage - subtle brightening
        isOnImage && !disabled && 'hover:bg-black/30 hover:border-white/30',

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
          // On-image: All icons are white/light for frosted glass look
          isOnImage && hasValue && 'text-emerald-400',
          isOnImage && !hasValue && tone === 'missing' && 'text-amber-400',
          isOnImage && !hasValue && tone !== 'missing' && 'text-white/60',
          !isOnImage && hasValue && 'text-[var(--chip-active-icon)]'
        )}
      />
      <span className="text-xs truncate max-w-[120px]">{displayText}</span>
      {hasValue && isOnImage && (
        // Glowing status dot for frosted glass pills
        <div className="w-1 h-1 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]" />
      )}
      {hasValue && !isOnImage && (
        <Check className="h-2.5 w-2.5 text-[var(--chip-active-icon)]" />
      )}
    </button>
  );
});

export default CoreChip;
