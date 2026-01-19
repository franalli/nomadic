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
}: ExpandablePillProps) {
  const handleOpenChange = (open: boolean) => {
    // Acknowledge LLM update when user opens the pill
    if (open && isLLMUpdated && onAcknowledge) {
      onAcknowledge();
    }
    onOpenChange(open);
  };

  // Icon color based on constraint state
  // Priority: open (editing) > conflict > set > unset
  const getIconColor = () => {
    if (isOpen) return 'text-[#FF8A00]';           // CTA Orange (editing)
    if (hasConflict) return 'text-[#C88A1E]';      // Conflict Amber
    if (hasValue) return 'text-[#E2A23A]';         // State Amber (set)
    return 'text-muted-foreground';                // Neutral (unset)
  };

  // Label color matches icon color for coherence
  const getLabelColor = () => {
    if (isOpen) return 'text-[#FF8A00]';
    if (hasConflict) return 'text-[#C88A1E]';
    if (hasValue) return 'text-[#E2A23A]';
    return 'text-muted-foreground';
  };

  // Echo overlay style for one-shot feedback
  const getEchoStyle = (): React.CSSProperties => {
    if (!isLLMUpdated || isOpen) return {};
    return {
      backgroundColor: 'rgba(255, 255, 255, 0.03)',
    };
  };

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'group inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 transition-all duration-200 ease-out active:scale-[0.98]',
            isOpen
              ? 'bg-primary/10 border border-[#FF8A00]/30 shadow-pill-active'
              : 'bg-gradient-to-b from-card to-muted/30 border border-border/50 shadow-pill hover:from-card hover:to-muted/50 hover:border-border/70 hover:shadow-pill-hover',
            // Conflict state: dashed border
            hasConflict && !isOpen && 'border-dashed border-[rgba(255,176,0,0.35)]'
          )}
          style={{
            ...getEchoStyle(),
            transition: isLLMUpdated
              ? 'all 100ms ease-out'
              : 'all 200ms ease-in',
          }}
        >
          <Icon
            className={cn('h-3.5 w-3.5 transition-colors duration-150', getIconColor())}
          />
          <span className={cn('text-xs font-semibold transition-colors duration-150', getLabelColor())}>
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
