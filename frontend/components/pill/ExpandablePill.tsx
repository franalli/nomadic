'use client';

import type { LucideIcon } from 'lucide-react';
import { ChevronDown } from 'lucide-react';
import { memo, type ReactNode } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ExpandablePillProps {
  /** Display label for the field (shown in the pill) */
  label: string;
  /** Icon component to display */
  icon: LucideIcon;
  /** Whether the expanded section is open */
  isOpen: boolean;
  /** Called when the expanded state changes */
  onOpenChange: (open: boolean) => void;
  /** Content to display when expanded (e.g., current value + input fields) */
  expandedContent: ReactNode;
  /** Use compact styling for simple single-input content */
  compact?: boolean;
  /** Whether this field has a value set (shows State Amber icon) */
  hasValue?: boolean;
  /** Whether this field is in conflict state (shows Conflict Amber icon) */
  hasConflict?: boolean;
  /** Whether this field was recently updated by the LLM (shows one-shot echo overlay) */
  isLLMUpdated?: boolean;
  /** Called when user clicks on the pill to acknowledge the LLM update */
  onAcknowledge?: () => void;
  /** Whether chip was just filled (triggers fill animation) */
  justFilled?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// ExpandablePill Component
//
// Icon color meanings (authoritative):
// - Neutral/muted: Constraint unset
// - State Amber (#E2A23A): Constraint set (steady)
// - CTA Orange (#FF8A00): Actively being edited (isOpen)
// - Conflict Amber (#C88A1E): Constraint conflicted
// ─────────────────────────────────────────────────────────────────────────────

function ExpandablePillInner({
  label,
  icon: Icon,
  isOpen,
  onOpenChange,
  expandedContent,
  compact = false,
  hasValue = false,
  hasConflict = false,
  isLLMUpdated = false,
  onAcknowledge,
  justFilled = false,
}: ExpandablePillProps) {
  const handleOpenChange = (open: boolean) => {
    // Acknowledge LLM update when user opens the pill
    if (open && isLLMUpdated && onAcknowledge) {
      onAcknowledge();
    }
    onOpenChange(open);
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Per YC Demo Chip Spec - Opacity-based state indication
  // Empty (cold start): text 0.72, border 0.35, bg 0.10
  // Hover (empty): text 0.88, border 0.55, bg 0.14
  // Active/Pressed: border 0.65, bg 0.18
  // Filled: text 0.92, border 0.60, bg 0.16, font-weight 600
  // ─────────────────────────────────────────────────────────────────────────

  // Icon color based on constraint state
  // Priority: open (editing) > conflict > set > unset
  const getIconColor = () => {
    if (isOpen) return 'text-[#FF8A00]';           // CTA Orange (editing)
    if (hasConflict) return 'text-[#C88A1E]';      // Conflict Amber
    if (hasValue) return 'text-[#E2A23A]';         // State Amber (set)
    return '';                                      // Uses parent opacity
  };

  // Echo overlay style for one-shot feedback
  const getEchoStyle = (): React.CSSProperties => {
    if (!isLLMUpdated || isOpen) return {};
    return {
      backgroundColor: 'var(--theme-surface-2)',
    };
  };

  // Chip fill animation keyframes (applied via data attribute)
  const fillAnimationStyle: React.CSSProperties = justFilled
    ? { animation: 'chipFill 160ms ease-out' }
    : {};

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-filled={hasValue}
          data-just-filled={justFilled}
          className={cn(
            // Base chip styles per spec: 28px height, 10px padding, pill shape
            'group inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full',
            'transition-all duration-[120ms] ease-out active:scale-[0.98]',
            // State-based styling (using theme tokens for light/dark mode)
            isOpen
              // Active/Open: higher contrast
              ? 'border border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)]'
              : hasValue
                // Filled: stronger presence, weight 600
                ? 'border border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] font-semibold'
                // Empty (subdued): lower contrast per spec
                : 'border border-[var(--theme-border)] bg-[var(--theme-surface-2)] text-[var(--theme-text-muted)] opacity-70',
            // Hover states
            !isOpen && !hasValue && 'hover:opacity-90 hover:bg-[var(--theme-overlay)]',
            !isOpen && hasValue && 'hover:opacity-100',
            // Conflict state: dashed border
            hasConflict && !isOpen && 'border-dashed border-[rgba(255,176,0,0.35)]',
            // Focus visible ring
            'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/65'
          )}
          style={{
            ...getEchoStyle(),
            ...fillAnimationStyle,
          }}
        >
          <Icon
            className={cn('h-3.5 w-3.5 transition-colors duration-150', getIconColor())}
          />
          <span className={cn(
            'text-xs transition-colors duration-150',
            hasValue ? 'font-semibold' : 'font-medium',
            getIconColor()
          )}>
            {label}
          </span>
          <ChevronDown
            className={cn(
              'h-3.5 w-3.5 transition-transform duration-200',
              isOpen ? 'rotate-180' : '',
              getIconColor()
            )}
          />
        </button>
      </PopoverTrigger>

      <PopoverContent
        className={cn(
          'rounded-xl border-border/40 bg-card/95 backdrop-blur-sm shadow-lg',
          compact ? 'p-2' : 'min-w-[180px] p-3'
        )}
        sideOffset={8}
        align="start"
      >
        {expandedContent}
      </PopoverContent>
    </Popover>
  );
}

export const ExpandablePill = memo(ExpandablePillInner);
