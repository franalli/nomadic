'use client';

import { ArrowUp, Calendar, Loader2, Sparkles } from 'lucide-react';
import { memo, useState } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MobilePlanFooterProps {
  /** Whether dates are set (determines CTA button type) */
  hasDates: boolean;
  /** Whether to show the CTA button (only in certain plan states) */
  showCta: boolean;
  /** Handler for "Create Itinerary" button */
  onBuildItinerary: () => void;
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
 * MobilePlanFooter - Sticky bottom dock with CTA + command line input.
 *
 * Replaces MinimizedChatInput on Plan/Book tabs with a more prominent CTA.
 * Structure:
 * - Layer 1: Primary CTA ("Create Itinerary" or "Select Dates")
 * - Layer 2: Command line input for making changes
 *
 * This ensures the primary action is always visible and never scrolls off-screen.
 */
function MobilePlanFooterInner({
  hasDates,
  showCta,
  onBuildItinerary,
  onSelectDates,
  onSendMessage,
  isProcessing = false,
  className,
}: MobilePlanFooterProps) {
  const [inputValue, setInputValue] = useState('');
  const { isDesktop, activeTab } = useMobileMode();

  // Only render on mobile, and specifically on Plan/Book tabs
  // Chat tab uses the standard ChatInput
  if (isDesktop || activeTab === 'chat') return null;

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
        // Position above the tab bar
        'bottom-[calc(var(--mobile-tab-bar-height,68px)+env(safe-area-inset-bottom))]',
        'flex flex-col gap-2 px-4 pb-4 pt-2',
        // Gradient fade to handle content scrolling underneath
        'bg-gradient-to-t from-background via-background/95 to-transparent',
        'lg:hidden',
        className
      )}
    >
      {/* LAYER 1: THE PRIMARY ACTION (Sticky CTA) */}
      {showCta && (
        <div className="w-full animate-in slide-in-from-bottom-2 fade-in duration-300">
          {hasDates ? (
            <button
              type="button"
              onClick={onBuildItinerary}
              disabled={isProcessing}
              className={cn(
                'w-full flex items-center justify-center gap-2',
                'bg-orange-500 hover:bg-orange-600 text-white',
                'font-medium py-3 rounded-xl',
                'shadow-lg shadow-orange-900/20',
                'active:scale-[0.98] transition-all',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              {isProcessing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              <span>Create day-by-day itinerary</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onSelectDates}
              className={cn(
                'w-full flex items-center justify-center gap-2',
                'bg-muted text-muted-foreground',
                'font-medium py-3 rounded-xl',
                'border border-border',
                'active:scale-[0.98] transition-all',
                'hover:bg-muted/80'
              )}
            >
              <Calendar className="w-4 h-4" />
              <span>Select dates to build plan</span>
            </button>
          )}
        </div>
      )}

      {/* LAYER 2: THE COMMAND LINE (Input Bar) */}
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
