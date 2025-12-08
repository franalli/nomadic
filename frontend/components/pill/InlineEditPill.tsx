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
  /** Whether this field was recently updated by the LLM (shows sparkle animation) */
  isLLMUpdated?: boolean;
  /** Called when user clicks on the pill to acknowledge the LLM update */
  onAcknowledge?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// InlineEditPill Component
// ─────────────────────────────────────────────────────────────────────────────

function InlineEditPillInner({
  label,
  icon: Icon,
  children,
  className,
  isLLMUpdated = false,
  onAcknowledge,
}: InlineEditPillProps) {
  const handleClick = () => {
    if (isLLMUpdated && onAcknowledge) {
      onAcknowledge();
    }
  };

  return (
    <div
      className={cn(
        'flex flex-col gap-1.5 rounded-2xl px-3 py-2.5',
        'bg-gradient-to-b from-card to-muted/20 border border-border/50',
        'shadow-pill h-full',
        isLLMUpdated && 'border-accent/40 shadow-pill-accent',
        className
      )}
      onClick={handleClick}
    >
      {/* Label row */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Icon
          className={cn(
            'h-3.5 w-3.5 text-muted-foreground',
            isLLMUpdated && 'sparkle-icon'
          )}
        />
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
      </div>
      {/* Content row - flex-1 to fill available space, items-start for top alignment */}
      <div className="flex flex-1 items-start content-start gap-2 flex-wrap">
        {children}
      </div>
    </div>
  );
}

export const InlineEditPill = memo(InlineEditPillInner);
