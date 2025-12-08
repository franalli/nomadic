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
  /** Whether this field was recently updated by the LLM (shows sparkle animation) */
  isLLMUpdated?: boolean;
  /** Called when user clicks on the pill to acknowledge the LLM update */
  onAcknowledge?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// ExpandablePill Component
// ─────────────────────────────────────────────────────────────────────────────

function ExpandablePillInner({
  label,
  icon: Icon,
  isOpen,
  onOpenChange,
  expandedContent,
  compact = false,
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

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'group inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 transition-all duration-200 ease-out active:scale-[0.98]',
            isOpen
              ? 'bg-primary/10 border border-primary/30 text-primary shadow-pill-active'
              : 'bg-gradient-to-b from-card to-muted/30 border border-border/50 text-muted-foreground shadow-pill hover:from-card hover:to-muted/50 hover:border-border/70 hover:shadow-pill-hover hover:text-foreground',
            isLLMUpdated && !isOpen && 'border-accent/40 shadow-pill-accent'
          )}
        >
          <Icon
            className={cn(
              'h-3.5 w-3.5',
              isLLMUpdated && !isOpen && 'sparkle-icon'
            )}
          />
          <span className="text-xs font-semibold">{label}</span>
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform duration-200 ${
              isOpen ? 'rotate-180' : ''
            }`}
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
