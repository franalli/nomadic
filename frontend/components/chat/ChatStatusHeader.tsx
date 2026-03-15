'use client';

/**
 * ChatStatusHeader — Desktop hero/status bar rendered at the top of ChatPanel.
 *
 * Two variants:
 * - Hero image mode: destination photo with gradient scrim
 * - Minimal mode: status text + indicator dot
 *
 * Shown only on desktop, only outside bootstrap state.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';

import { isBootstrap, ITINERARY_STATES } from '@/components/plan/planStateHelpers';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { PlanViewState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Chat Status Config - maps plan phase to persistent status bar content
// ─────────────────────────────────────────────────────────────────────────────
export function getChatStatusConfig(
  planViewState: PlanViewState | undefined | null,
  planState: string | undefined,
  isGenerating: boolean,
  destination: string | undefined,
  hasDates: boolean,
  /** UI loading signal — replaces the old isFraming(planViewState) check */
  isFramingOverride?: boolean,
): { text: string; label: string; indicator: 'blink' | 'spin' | 'pulse' | 'check' } {
  if (isFramingOverride || isGenerating || planState === 'RESOLVING') {
    return { text: 'Building your trip...', label: 'Generating', indicator: 'spin' };
  }
  if (isBootstrap(planViewState)) {
    if (!destination) return { text: 'Where to next?', label: 'Awaiting Input', indicator: 'blink' };
    if (!hasDates) return { text: 'When would you like to go?', label: 'Set Dates', indicator: 'blink' };
    return { text: 'Ready to build your plan', label: 'Generating Plan', indicator: 'blink' };
  }
  if (planViewState && ITINERARY_STATES.has(planViewState)) {
    return { text: 'Itinerary complete', label: 'Ready', indicator: 'check' };
  }
  return { text: 'Your trip is taking shape', label: 'Refine Plan', indicator: 'pulse' };
}

// Hoisted Framer Motion animation objects to avoid new object identity on every render
const FADE_INITIAL = { opacity: 0 } as const;
const FADE_ANIMATE = { opacity: 1 } as const;
const FADE_EXIT = { opacity: 0 } as const;
const FADE_TRANSITION = { duration: 0.3, ease: [0.4, 0, 0.2, 1] } as const;

interface ChatStatusHeaderProps {
  planViewState: PlanViewState | undefined | null;
  /** UI loading signal: backend state not yet received but generation is active. */
  isFraming?: boolean;
  planState: string | undefined;
  isGenerating: boolean;
  destination: string | undefined;
  hasDates: boolean;
  hasDestination: boolean;
  destinationImageUrl?: string | null;
}

export function ChatStatusHeader({
  planViewState,
  isFraming: isFramingProp,
  planState,
  isGenerating,
  destination,
  hasDates,
  hasDestination,
  destinationImageUrl,
}: ChatStatusHeaderProps) {
  if (isBootstrap(planViewState) && !isFramingProp) return null;

  const status = getChatStatusConfig(planViewState, planState, isGenerating, destination, hasDates, isFramingProp);
  const showHero = !!(destinationImageUrl && hasDestination);

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key="status-bar"
        initial={FADE_INITIAL}
        animate={FADE_ANIMATE}
        exit={FADE_EXIT}
        transition={FADE_TRANSITION}
        className={cn(
          'relative z-40 shrink-0',
          'mb-2 overflow-hidden',
          showHero
            ? '-mx-2 -mt-5 h-[120px] w-[calc(100%+1rem)]'
            : '-mx-4 -mt-4 w-[calc(100%+2rem)] h-14 border-b border-zinc-200/80 dark:border-white/10 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-md',
        )}
      >
        {/* Hero image — only when destination image available */}
        {showHero && (
          <div className="relative h-full overflow-hidden rounded-2xl ring-1 ring-white/10 shadow-[0_8px_30px_rgba(0,0,0,0.4)]">
            <img
              src={destinationImageUrl!}
              alt={destination ?? 'Destination'}
              className="h-full w-full object-cover brightness-90 saturate-[1.1]"
            />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-zinc-950/80 via-zinc-950/20 to-transparent" />
          </div>
        )}
        {!showHero && (
          <div className="absolute inset-0 z-10 flex items-center gap-2 px-4">
            {status.indicator === 'spin' ? (
              <Loader2 className="h-3 w-3 animate-spin text-emerald-600 dark:text-emerald-500" />
            ) : status.indicator === 'check' ? null : (
              <div className={cn(
                'h-2 w-2 rounded-full bg-emerald-600 dark:bg-emerald-500',
                status.indicator === 'pulse' && 'animate-pulse',
              )} />
            )}
            <span className="text-sm font-semibold text-zinc-900 dark:text-white">
              {status.text}
            </span>
            <span className={cn(
              `font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-zinc-500 dark:text-zinc-400`,
              `dark:${DS.glowClass.dropText}`,
            )}>
              {status.label}
            </span>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
