'use client';

import type { LucideIcon } from 'lucide-react';
import { memo, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface InlineEditPillProps {
  /** Display label for the field (shown in the pill) */
  label: string;
  /** Icon component to display */
  icon: LucideIcon;
  /** Content to display inline (inputs, badges, etc.) */
  children: ReactNode;
  /** Additional className for the container */
  className?: string;
  /** Whether this field has a value set (shows State Amber icon) */
  hasValue?: boolean;
  /** Whether this field is in conflict state (shows Conflict Amber icon + dashed border) */
  hasConflict?: boolean;
  /** Whether this field was recently updated by the LLM (shows one-shot echo overlay) */
  isLLMUpdated?: boolean;
  /** Called when user clicks on the pill to acknowledge the LLM update */
  onAcknowledge?: () => void;
  /** Whether this field has a validation error */
  hasError?: boolean;
  /** Whether this pill was just filled (triggers fill animation) */
  justFilled?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// InlineEditPill Component
//
// Icon color meanings (authoritative):
// - Neutral/muted: Constraint unset
// - State Amber (#E2A23A): Constraint set (steady)
// - Conflict Amber (#C88A1E) + dashed border: Constraint conflicted
//
// Echo overlay timings:
// - Fade in: 100ms ease-out
// - Fade out: 200ms ease-in
// - Total: 300ms
//
// No pulsing, no "Got it!" popup. One-shot state change only.
// ─────────────────────────────────────────────────────────────────────────────

function InlineEditPillInner({
  label,
  icon: Icon,
  children,
  className,
  hasValue = false,
  hasConflict = false,
  isLLMUpdated = false,
  onAcknowledge,
  hasError = false,
  justFilled = false,
}: InlineEditPillProps) {
  const handleClick = () => {
    if (isLLMUpdated && onAcknowledge) {
      onAcknowledge();
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Per YC Demo Chip Spec - Opacity-based state indication
  // Empty (cold start): text 0.72, border 0.35, bg 0.10
  // Filled: text 0.92, border 0.60, bg 0.16, font-weight 600
  // ─────────────────────────────────────────────────────────────────────────

  // Icon color based on constraint state (not LLM update status)
  // Priority: conflict > set > unset
  const getIconColor = () => {
    if (hasConflict) return 'text-[#C88A1E]';                  // Conflict Amber
    if (hasValue) return 'text-[var(--chip-active-icon)]';    // Teal accent (set)
    return '';                                                  // Uses parent color
  };

  // Echo overlay for causal feedback (one-shot, 300ms total)
  const getEchoStyle = (): React.CSSProperties => {
    if (!isLLMUpdated) return {};
    if (hasConflict) {
      return {
        backgroundColor: 'rgba(255, 176, 0, 0.06)',
        borderStyle: 'dashed',
        borderColor: 'rgba(255, 176, 0, 0.35)',
      };
    }
    return {
      backgroundColor: 'var(--theme-surface-2)',
    };
  };

  // Chip fill animation
  const fillAnimationStyle: React.CSSProperties = justFilled
    ? { animation: 'chipFill 160ms ease-out' }
    : {};

  return (
    <div
      data-filled={hasValue}
      data-just-filled={justFilled}
      className={cn(
        'flex flex-col gap-1.5 rounded-2xl px-3 py-2.5 relative overflow-visible',
        'transition-all duration-[120ms] ease-out h-full',
        // State-based styling using chip tokens
        hasValue
          // Active/Filled state: accent tint, stronger presence
          ? 'border border-[var(--chip-active-border)] bg-[var(--chip-active-bg)] text-[var(--chip-active-text)] font-semibold'
          // Inactive/Default state: subtle, clickable appearance
          : 'border border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)]',
        // Hover state for empty pills
        !hasValue && 'hover:border-[var(--chip-border-hover)]',
        // Conflict state: dashed amber border
        hasConflict && 'border-dashed border-[rgba(255,176,0,0.45)]',
        hasError && 'border-destructive/50 bg-destructive/5',
        // Focus visible ring
        'focus-within:ring-1 focus-within:ring-[var(--chip-active-icon)]/50',
        className
      )}
      style={{
        ...getEchoStyle(),
        ...fillAnimationStyle,
      }}
      onClick={handleClick}
    >
      {/* Label row */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Icon
          className={cn('h-3.5 w-3.5 transition-colors duration-150', getIconColor())}
        />
        <span
          className={cn(
            'text-xs transition-colors duration-150',
            hasValue ? 'font-semibold' : 'font-medium',
            hasConflict ? 'text-[#C88A1E]' : hasValue ? 'text-[#E2A23A]' : ''
          )}
        >
          {label}
        </span>
      </div>
      {/* Content row - flex-1 to fill available space, items-start for top alignment */}
      <div className="flex flex-1 items-start content-start gap-2 flex-wrap">
        {children}
      </div>
    </div>
  );
}

export const InlineEditPill = memo(InlineEditPillInner);
