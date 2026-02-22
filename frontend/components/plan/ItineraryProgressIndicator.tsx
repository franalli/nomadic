/**
 * ItineraryProgressIndicator
 *
 * Shows auto-progress indicator during itinerary generation.
 * Replaces Build button for multi-specialist trips (Path A UX).
 *
 * States:
 * - analyzing: "Analyzing diving + hiking requirements..."
 * - conflict_detected: Shows conflict banner
 * - success: Timeline appears (handled by parent)
 *
 * @see docs/ux_unified_architecture.md - Path A: Auto-trigger flow
 */

'use client';

import { motion } from 'framer-motion';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';

/** Fallback width for indeterminate progress bar animation */
const INDETERMINATE_PROGRESS_STYLE = { width: '30%' } as const;

export type ProgressStage = 'analyzing' | 'checking' | 'building' | 'conflict_detected' | 'success' | 'error';

interface ItineraryProgressIndicatorProps {
  /** Current progress stage */
  stage: ProgressStage;
  /** Active specialist types being processed */
  specialists?: string[];
  /** Progress percentage (0-100) */
  progress?: number;
  /** Custom message override */
  message?: string;
  /** Error message when stage is 'error' */
  errorMessage?: string;
  /** Callback for retry action */
  onRetry?: () => void;
  className?: string;
}

const STAGE_MESSAGES: Record<ProgressStage, string> = {
  analyzing: 'Analyzing requirements...',
  checking: 'Checking constraints',
  building: 'Building timeline...',
  conflict_detected: 'Constraint conflict detected',
  success: 'Timeline ready',
  error: 'Generation failed',
};

export function ItineraryProgressIndicator({
  stage,
  specialists = [],
  progress,
  message,
  errorMessage,
  onRetry,
  className,
}: ItineraryProgressIndicatorProps) {
  const isActive = stage !== 'success' && stage !== 'conflict_detected' && stage !== 'error';
  const isError = stage === 'error';
  const isConflict = stage === 'conflict_detected';

  // Build display message
  const displayMessage = message ?? (() => {
    if (stage === 'analyzing' && specialists.length > 1) {
      return `Analyzing ${specialists.join(' + ')} requirements...`;
    }
    return STAGE_MESSAGES[stage];
  })();

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
      className={cn(
        'w-full p-4 rounded-xl',
        'bg-zinc-100/80 dark:bg-zinc-900/50 backdrop-blur-sm',
        'border',
        isError
          ? 'border-red-400/40 dark:border-red-500/30'
          : isConflict
            ? 'border-amber-400/40 dark:border-amber-500/30'
            : 'border-emerald-400/40 dark:border-emerald-500/20',
        className
      )}
    >
      <div className="flex items-center gap-3">
        {/* Status Icon */}
        {isActive && (
          <Loader2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 animate-spin shrink-0" />
        )}
        {stage === 'success' && (
          <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
        )}
        {isConflict && (
          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
        )}
        {isError && (
          <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400 shrink-0" />
        )}

        {/* Message */}
        <div className="flex-1 min-w-0">
          <span
            className={cn(
              'text-sm font-medium',
              isError
                ? 'text-red-600 dark:text-red-400'
                : isConflict
                  ? 'text-amber-600 dark:text-amber-400'
                  : 'text-zinc-700 dark:text-zinc-200'
            )}
          >
            {displayMessage}
          </span>

          {/* Error details */}
          {isError && errorMessage && (
            <p className="text-xs text-red-500/70 dark:text-red-400/70 mt-1">{errorMessage}</p>
          )}
        </div>

        {/* Retry button for errors */}
        {isError && onRetry && (
          <button
            onClick={onRetry}
            className="px-3 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 underline"
          >
            Retry
          </button>
        )}
      </div>

      {/* Progress bar (only during active states) */}
      {isActive && (
        <div className="mt-3 h-1 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-emerald-500 rounded-full"
            initial={{ width: '0%' }}
            animate={{
              width: progress != null ? `${progress}%` : '100%',
            }}
            transition={
              progress != null
                ? { duration: 0.3 }
                : {
                    repeat: Infinity,
                    repeatType: 'reverse',
                    duration: 1.5,
                    ease: 'easeInOut',
                  }
            }
            style={
              progress == null
                ? INDETERMINATE_PROGRESS_STYLE
                : undefined
            }
          />
        </div>
      )}
    </motion.div>
  );
}

export default ItineraryProgressIndicator;
