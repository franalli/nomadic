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

interface CoreChipProps {
  icon: LucideIcon;
  label: string;              // "Dates"
  value?: string | null;      // "Dec 15-22" (pre-formatted)
  placeholder?: string;       // "Add dates" (shown when no value)
  onClick?: () => void;
  tone?: 'default' | 'missing' | 'optional';
  disabled?: boolean;         // Disable during streaming/loading
  /** Use 'onImage' when chip is on a hero/photo background */
  variant?: 'default' | 'onImage';
  /** Optional className override for visual hierarchy */
  className?: string;
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
  className,
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
        // Base transition
        'transition-all duration-[120ms] ease-out active:scale-[0.98]',
        // Disabled state
        disabled && 'opacity-50 cursor-not-allowed pointer-events-none',

        // === ON-IMAGE VARIANT (for hero/photo backgrounds) ===
        // Larger, touch-friendly sizing for hero pills
        isOnImage && 'inline-flex items-center gap-2 h-8 px-3.5 rounded-full border text-xs',
        // HIGH-CONTRAST GLASS: Darker backing for better readability on busy images
        isOnImage && hasValue && 'border-white/30 bg-black/60 backdrop-blur-md text-white font-semibold shadow-lg',
        isOnImage && !hasValue && tone === 'missing' && 'border-zinc-400/50 border-dashed bg-black/50 backdrop-blur-md text-white/95 shadow-lg',
        isOnImage && !hasValue && tone === 'optional' && 'border-white/25 bg-black/45 backdrop-blur-md text-white/80 shadow-lg',
        isOnImage && !hasValue && tone === 'default' && 'border-white/30 bg-black/50 backdrop-blur-md text-white/90 shadow-lg',
        // Hover/active for onImage - subtle brightening with tap feedback
        isOnImage && !disabled && 'hover:bg-black/70 hover:border-white/40 active:bg-black/75',

        // === DEFAULT VARIANT (for normal page backgrounds) ===
        // Compact sizing for non-hero contexts
        !isOnImage && 'inline-flex items-center gap-1.5 h-8 px-3.5 rounded-full border text-sm shadow-none hover:shadow-none',

        // === DEFAULT VARIANT (for normal page backgrounds) ===
        !isOnImage && hasValue && 'border-[var(--chip-active-border)] bg-[var(--chip-active-bg)] text-[var(--chip-active-text)] font-semibold',
        !isOnImage && !hasValue && tone === 'missing' && 'border-dashed border-zinc-400/50 bg-zinc-500/5 text-zinc-400',
        !isOnImage && !hasValue && tone === 'optional' && 'border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)]',
        !isOnImage && !hasValue && tone === 'default' && 'border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)]',
        // Hover — border + subtle fill
        !isOnImage && !disabled && !hasValue && 'hover:bg-[var(--chip-bg-hover)] hover:border-[var(--chip-border-hover)]',
        !isOnImage && !disabled && hasValue && 'hover:bg-[var(--chip-bg-hover)] hover:border-[var(--chip-active-border)]',

        // Focus ring
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--chip-active-icon)]/50',
        // Custom className override
        className
      )}
    >
      <Icon
        className={cn(
          'flex-shrink-0',
          // Size varies by variant
          isOnImage ? 'h-4 w-4' : 'h-3.5 w-3.5',
          // Icon color based on variant and state
          // On-image: All icons are white/light for frosted glass look
          isOnImage && hasValue && 'text-emerald-400',
          isOnImage && !hasValue && tone === 'missing' && 'text-zinc-400',
          isOnImage && !hasValue && tone !== 'missing' && 'text-white/60',
          !isOnImage && hasValue && 'text-[var(--chip-active-icon)]'
        )}
      />
      <span className={cn(
        'truncate',
        isOnImage ? 'max-w-[140px]' : 'max-w-[120px]'
      )}>
        {displayText}
      </span>
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
