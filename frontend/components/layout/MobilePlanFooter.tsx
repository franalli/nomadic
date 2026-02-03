'use client';

import { ArrowUp } from 'lucide-react';
import { memo, useState } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MobilePlanFooterProps {
  /** Handler for "Select Dates" button */
  onSelectDates: () => void;
  /** Handler for sending message from input */
  onSendMessage: (message: string) => void;
  /** Whether a message is being processed */
  isProcessing?: boolean;
  /** Additional CSS classes */
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * MobilePlanFooter - Command line input for mobile plan mode.
 *
 * Design: Sticky Bar Pattern (per user spec)
 * - Position: Above chat bar, within thumb zone
 * - RefreshButton FAB handles regeneration - CTA removed
 *
 * Structure:
 * ┌─────────────────────────────────────────┐
 * │ Type changes...                         │  ← Command input
 * └─────────────────────────────────────────┘
 */
function MobilePlanFooterInner({
  onSelectDates: _onSelectDates, // Kept for future use
  onSendMessage,
  isProcessing = false,
  className,
}: MobilePlanFooterProps) {
  void _onSelectDates; // Silence unused warning
  const [inputValue, setInputValue] = useState('');
  const { isDesktop, mode } = useMobileMode();

  // Only render on mobile when in plan mode (not planner/chat mode)
  if (isDesktop || mode === 'planner') return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim() && !isProcessing) {
      onSendMessage(inputValue.trim());
      setInputValue('');
    }
  };

  return (
    <div
      className={cn(
        'fixed left-0 right-0 z-[1001]',
        // Position above the tab bar (thumb zone)
        'bottom-[calc(var(--mobile-tab-bar-height,68px)+env(safe-area-inset-bottom))]',
        'flex flex-col gap-2 px-4 pb-3 pt-2',
        // Glass effect
        'bg-gradient-to-t from-background via-background/95 to-transparent',
        'lg:hidden',
        className
      )}
    >
      {/* CTA removed - RefreshButton FAB handles regeneration */}

      {/* COMMAND LINE INPUT */}
      <form onSubmit={handleSubmit} className="relative w-full">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Type changes, e.g. 'Add a rest day'..."
          disabled={isProcessing}
          className={cn(
            'w-full bg-muted/90 backdrop-blur-md',
            'border border-border/50',
            'text-foreground placeholder:text-muted-foreground/60',
            'pl-4 pr-10 py-3 rounded-full text-sm',
            'focus:outline-none focus:ring-1 focus:ring-primary/50',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'shadow-sm'
          )}
          aria-label="Type changes to your plan"
        />
        <button
          type="submit"
          disabled={!inputValue.trim() || isProcessing}
          className={cn(
            'absolute right-2 top-1/2 -translate-y-1/2',
            'p-1.5 bg-background/50 rounded-full',
            'text-muted-foreground hover:text-primary',
            'transition-colors',
            'disabled:opacity-30 disabled:cursor-not-allowed'
          )}
          aria-label="Send message"
        >
          <ArrowUp className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}

export const MobilePlanFooter = memo(MobilePlanFooterInner);
