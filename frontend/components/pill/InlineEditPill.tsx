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
}: InlineEditPillProps) {
  const handleClick = () => {
    if (isLLMUpdated && onAcknowledge) {
      onAcknowledge();
    }
  };

  // Icon color based on constraint state (not LLM update status)
  // Priority: conflict > set > unset
  const getIconColor = () => {
    if (hasConflict) return 'text-[#C88A1E]';    // Conflict Amber
    if (hasValue) return 'text-[#E2A23A]';       // State Amber (set)
    return 'text-muted-foreground';              // Neutral (unset)
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
      backgroundColor: 'rgba(255, 255, 255, 0.03)',
    };
  };

  return (
    <div
      className={cn(
        'flex flex-col gap-1.5 rounded-2xl px-3 py-2.5 relative overflow-visible',
        'bg-gradient-to-b from-card to-muted/20 border border-border/50',
        'shadow-pill h-full',
        // Conflict state: dashed border
        hasConflict && 'border-dashed border-[rgba(255,176,0,0.35)]',
        hasError && 'border-destructive/50 bg-destructive/5',
        className
      )}
      style={{
        ...getEchoStyle(),
        transition: isLLMUpdated
          ? 'all 100ms ease-out'
          : 'all 200ms ease-in',
      }}
      onClick={handleClick}
    >
      {/* Label row */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Icon
          className={cn('h-3.5 w-3.5', getIconColor())}
          style={{ transition: 'color 150ms linear' }}
        />
        <span
          className={cn(
            'text-xs font-medium',
            hasConflict ? 'text-[#C88A1E]' : hasValue ? 'text-[#E2A23A]' : 'text-muted-foreground'
          )}
          style={{ transition: 'color 150ms linear' }}
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
