'use client';

import { ArrowUp, Calendar, ChevronRight, Loader2, Zap } from 'lucide-react';
import { memo, useState } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { useTripValidation } from '@/hooks/useTripValidation';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';

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
 * MobilePlanFooter - Compact sticky bar with CTA + command line input.
 *
 * Design: Sticky Bar Pattern (per user spec)
 * - 48dp height, single line
 * - Inline context: duration + specialist count
 * - State-aware: amber (needs dates), emerald (ready), muted (building)
 * - Position: Above chat bar, within thumb zone
 *
 * Structure:
 * ┌─────────────────────────────────────────┐
 * │ ⚡ Build (4d • 2 specs)              → │  ← Sticky CTA bar
 * ├─────────────────────────────────────────┤
 * │ Type changes...                         │  ← Command input
 * └─────────────────────────────────────────┘
 */
function MobilePlanFooterInner({
  hasDates: _hasDates, // Kept for API compat, validation handled by useTripValidation
  showCta,
  onBuildItinerary,
  onSelectDates,
  onSendMessage,
  isProcessing = false,
  className,
}: MobilePlanFooterProps) {
  void _hasDates; // Silence unused warning - validation now handled by useTripValidation hook
  const [inputValue, setInputValue] = useState('');
  const { isDesktop, activeTab } = useMobileMode();

  // Unified validation state
  const validation = useTripValidation();

  // Get specialist count from strategy sections
  const strategySections = useDocumentStore((s) => s.document?.strategy_sections);
  const specialistCount = strategySections?.length ?? 0;

  // Only render on mobile, and specifically on Plan/Book tabs
  if (isDesktop || activeTab === 'chat') return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim() && !isProcessing) {
      onSendMessage(inputValue.trim());
      setInputValue('');
    }
  };

  // Compute state for styling
  const isReady = validation.valid && !isProcessing;
  const needsDates = !validation.valid && validation.reason !== 'no_destination';
  const isBuilding = isProcessing;

  // Build context string: "4d • 2 specs" or just "4d"
  const contextParts: string[] = [];
  if (validation.duration) {
    contextParts.push(`${validation.duration}d`);
  }
  if (specialistCount > 0) {
    contextParts.push(`${specialistCount} spec${specialistCount > 1 ? 's' : ''}`);
  }
  const contextString = contextParts.join(' • ');

  // Handle CTA click
  const handleCtaClick = () => {
    if (isBuilding) return;
    if (needsDates) {
      onSelectDates();
    } else {
      onBuildItinerary();
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
      {/* STICKY CTA BAR (48dp height, single line) */}
      {showCta && (
        <button
          type="button"
          onClick={handleCtaClick}
          disabled={isBuilding}
          className={cn(
            // Layout: 48dp height, flex row
            'h-12 w-full flex items-center justify-between',
            'px-4 rounded-xl',
            // Glass material
            'backdrop-blur-md border',
            'transition-all duration-200',
            'active:scale-[0.98]',
            'disabled:cursor-not-allowed',
            // State-aware styling
            isReady && [
              'bg-emerald-500/95 border-emerald-400/30',
              'text-white',
              'shadow-lg shadow-emerald-500/20',
            ],
            needsDates && [
              'bg-amber-500/95 border-amber-400/30',
              'text-white',
              'shadow-lg shadow-amber-500/20',
            ],
            isBuilding && [
              'bg-zinc-200/90 dark:bg-zinc-800/90',
              'border-zinc-300/50 dark:border-zinc-700/50',
              'text-zinc-500 dark:text-zinc-400',
            ]
          )}
        >
          {/* Left: Icon + Label + Context */}
          <div className="flex items-center gap-2">
            {/* Icon */}
            {isBuilding ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : needsDates ? (
              <Calendar className="w-4 h-4" />
            ) : (
              <Zap className="w-4 h-4" />
            )}

            {/* Label */}
            <span className="font-semibold text-sm">
              {isBuilding
                ? 'Building...'
                : needsDates
                  ? validation.action
                  : 'Build'}
            </span>

            {/* Context: duration + specialists */}
            {!isBuilding && contextString && (
              <>
                <span className="opacity-50">•</span>
                <span className="text-sm opacity-80">{contextString}</span>
              </>
            )}
          </div>

          {/* Right: Arrow indicator (or spinner progress) */}
          {isBuilding ? (
            <span className="text-xs opacity-60">Generating...</span>
          ) : (
            <ChevronRight className="w-4 h-4 opacity-70" />
          )}
        </button>
      )}

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
