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

import { isBootstrap, isFraming, ITINERARY_STATES } from '@/components/plan/planStateHelpers';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { PlanViewState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Chat Status Config - maps plan phase to persistent status bar content
// ─────────────────────────────────────────────────────────────────────────────
export function getChatStatusConfig(
  planViewState: PlanViewState | undefined,
  planState: string | undefined,
  isGenerating: boolean,
  destination: string | undefined,
  hasDates: boolean,
): { text: string; label: string; indicator: 'blink' | 'spin' | 'pulse' | 'check' } {
  if (isFraming(planViewState) || isGenerating || planState === 'RESOLVING') {
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
  planViewState: PlanViewState | undefined;
  planState: string | undefined;
  isGenerating: boolean;
  destination: string | undefined;
  hasDates: boolean;
  hasDestination: boolean;
  destinationImageUrl?: string | null;
}

export function ChatStatusHeader({
  planViewState,
  planState,
  isGenerating,
  destination,
  hasDates,
  hasDestination,
  destinationImageUrl,
}: ChatStatusHeaderProps) {
  if (isBootstrap(planViewState)) return null;

  const status = getChatStatusConfig(planViewState, planState, isGenerating, destination, hasDates);
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
          '-mx-4 -mt-4 mb-2',
          'w-[calc(100%+2rem)]',
          'overflow-hidden',
          showHero
            ? 'h-[120px]'
            : 'h-14 border-b border-border/80 bg-background/80 backdrop-blur-md',
        )}
      >
        {/* Hero image — only when destination image available */}
        {showHero && (
          <img
            src={destinationImageUrl!}
            alt={destination}
            className="absolute inset-0 h-full w-full object-cover brightness-90 saturate-[1.1]"
          />
        )}
        {/* Scrim: bottom half fades hard to panel background, top stays clear */}
        {showHero && (
          <div className="absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-black/60 to-transparent pointer-events-none" />
        )}
        {!showHero && (
          <div className="absolute inset-0 z-10 flex items-center gap-2 px-4">
            {status.indicator === 'spin' ? (
              <Loader2 className="h-3 w-3 animate-spin text-primary" />
            ) : status.indicator === 'check' ? null : (
              <div className={cn(
                'h-2 w-2 rounded-full bg-primary',
                status.indicator === 'pulse' && 'animate-pulse',
              )} />
            )}
            <span className="text-sm font-semibold text-foreground">
              {status.text}
            </span>
            <span className={cn(
              `font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-muted-foreground`,
              DS.glowClass.dropText,
            )}>
              {status.label}
            </span>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
