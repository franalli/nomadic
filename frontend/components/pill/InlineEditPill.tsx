'use client';

import type { LucideIcon } from 'lucide-react';
import { Check } from 'lucide-react';
import { memo, type ReactNode,useEffect, useState } from 'react';

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
  /** Whether this field has a validation error */
  hasError?: boolean;
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
  hasError = false,
}: InlineEditPillProps) {
  // Track when isLLMUpdated transitions from false to true for animation
  const [showGotIt, setShowGotIt] = useState(false);
  const [wasUpdated, setWasUpdated] = useState(false);

  useEffect(() => {
    // Show "Got it!" badge when field is newly updated
    if (isLLMUpdated && !wasUpdated) {
      setShowGotIt(true);
      // Auto-hide after 2 seconds
      const timer = setTimeout(() => setShowGotIt(false), 2000);
      return () => clearTimeout(timer);
    }
    // Hide badge immediately when field is no longer LLM-updated (e.g., after undo)
    if (!isLLMUpdated && wasUpdated) {
      setShowGotIt(false);
    }
    setWasUpdated(isLLMUpdated);
  }, [isLLMUpdated, wasUpdated]);

  const handleClick = () => {
    if (isLLMUpdated && onAcknowledge) {
      onAcknowledge();
      setShowGotIt(false);
    }
  };

  return (
    <div
      className={cn(
        'flex flex-col gap-1.5 rounded-2xl px-3 py-2.5 relative overflow-visible',
        'bg-gradient-to-b from-card to-muted/20 border border-border/50',
        'shadow-pill h-full transition-all duration-300',
        isLLMUpdated && 'border-accent/40 shadow-pill-accent ring-1 ring-accent/20',
        hasError && 'border-destructive/50 bg-destructive/5',
        className
      )}
      onClick={handleClick}
    >
      {/* "Got it!" badge - shows briefly when field is extracted */}
      {showGotIt && (
        <div
          className="absolute -top-2 -right-2 z-50 flex items-center gap-0.5 bg-accent text-accent-foreground text-[10px] font-semibold px-1.5 py-0.5 rounded-full animate-in fade-in zoom-in-95 duration-200 shadow-sm"
        >
          <Check className="h-2.5 w-2.5" />
          <span>Got it!</span>
        </div>
      )}
      {/* Label row */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Icon
          className={cn(
            'h-3.5 w-3.5 text-muted-foreground transition-colors duration-200',
            isLLMUpdated && 'text-accent sparkle-icon'
          )}
        />
        <span className={cn(
          'text-xs font-medium text-muted-foreground transition-colors duration-200',
          isLLMUpdated && 'text-accent'
        )}>
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
