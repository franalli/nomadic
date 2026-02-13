/**
 * StartupSequence
 *
 * Cinematic boot sequence for the Nomadic app.
 * Bifurcated aesthetic: "System Online" (Dark) vs "Blueprint Initialization" (Light)
 *
 * Features:
 * - Phase 1: Terminal text types "INITIALIZING_ARCHITECT_CORE_V3.0..."
 * - Phase 2: Topographic grid pulses into view
 * - Phase 3: Skeletal loaders verify (fall from top on desktop, slide from right on mobile)
 * - Phase 4: Beacon dot expands as "eye opening"
 * - Respects prefers-reduced-motion (skips entire sequence)
 * - Session persistence (only runs once per session via sessionStorage)
 */

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { memo, useCallback, useEffect, useState } from 'react';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import { cn } from '@/lib/utils';

import { Typewriter } from './Typewriter';

interface StartupSequenceProps {
  onComplete: () => void;
}

// Session flag to prevent re-running on navigation
const SESSION_KEY = 'nomadic_has_booted';

export const StartupSequence = memo(function StartupSequence({
  onComplete,
}: StartupSequenceProps) {
  const isDesktop = useIsDesktop();
  const [phase, setPhase] = useState<'typing' | 'grid' | 'verify' | 'beacon' | 'done'>('typing');
  const [isVisible, setIsVisible] = useState(true);
  const [shouldSkip, setShouldSkip] = useState(false);

  // Check if already booted this session or reduced motion preferred
  useEffect(() => {
    if (typeof window === 'undefined') return;

    // Check session storage
    if (sessionStorage.getItem(SESSION_KEY)) {
      setShouldSkip(true);
      setIsVisible(false);
      onComplete();
      return;
    }

    // Check reduced motion preference
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) {
      sessionStorage.setItem(SESSION_KEY, 'true');
      setShouldSkip(true);
      setIsVisible(false);
      onComplete();
    }
  }, [onComplete]);

  // Phase progression
  const handleTypingComplete = useCallback(() => {
    setTimeout(() => setPhase('grid'), 200);
  }, []);

  useEffect(() => {
    if (shouldSkip) return;

    const timers: ReturnType<typeof setTimeout>[] = [];

    if (phase === 'grid') {
      timers.push(setTimeout(() => setPhase('verify'), 700));
    } else if (phase === 'verify') {
      timers.push(setTimeout(() => setPhase('beacon'), 1000));
    } else if (phase === 'beacon') {
      timers.push(setTimeout(() => {
        setPhase('done');
        sessionStorage.setItem(SESSION_KEY, 'true');
        timers.push(setTimeout(() => {
          setIsVisible(false);
          onComplete();
        }, 500));
      }, 700));
    }

    return () => timers.forEach(clearTimeout);
  }, [phase, onComplete, shouldSkip]);

  if (!isVisible || shouldSkip) return null;

  return (
    <AnimatePresence>
      {phase !== 'done' && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className={cn(
            'fixed inset-0 z-[9999] flex flex-col items-center justify-center',
            'font-mono select-none',
            // Light Mode: Drafting Paper
            'bg-zinc-50',
            // Dark Mode: Deep Void
            'dark:bg-zinc-950'
          )}
        >
          {/* 1. TOPOGRAPHIC GRID (Phase 2+) */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: phase !== 'typing' ? 1 : 0 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className="absolute inset-0 overflow-hidden pointer-events-none"
          >
            <div
              className={cn(
                'absolute inset-0',
                "bg-[url('/assets/contours.svg')] bg-center bg-repeat",
                // Light: Subtle graph paper
                'opacity-[0.03]',
                // Dark: Laser grid
                'dark:opacity-[0.05]',
                '[mask-image:linear-gradient(180deg,white,rgba(255,255,255,0))]'
              )}
            />
          </motion.div>

          {/* 2. TERMINAL TEXT */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.3 }}
            className={cn(
              'z-10 mb-8',
              // Typography: DS.text.label pattern (per Section 17)
              'font-mono text-[10px] font-bold uppercase tracking-[0.2em]',
              isDesktop && 'text-xs',
              // Light: "Typewriter Ink" - Solid Black (per Section 17)
              'text-zinc-950',
              // Dark: "System Pulse" - Emerald with glow (per Section 17)
              'dark:text-emerald-500 dark:drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]'
            )}
          >
            <Typewriter
              text="INITIALIZING_ARCHITECT_CORE_V3.0..."
              speed={35}
              onComplete={handleTypingComplete}
            />
          </motion.div>

          {/* 3. VERIFICATION LOADERS (Phase 3+) */}
          <div className="flex gap-2 h-8 items-center z-10">
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                initial={{
                  opacity: 0,
                  y: isDesktop ? -20 : 0,
                  x: isDesktop ? 0 : 20,
                }}
                animate={{
                  opacity: phase === 'verify' || phase === 'beacon' ? 1 : 0,
                  y: 0,
                  x: 0,
                }}
                transition={{
                  delay: 0.1 * i,
                  type: 'spring',
                  stiffness: 400,
                  damping: 25,
                }}
                className={cn(
                  'w-12 h-2 rounded-full overflow-hidden',
                  // Light: Grey skeleton
                  'bg-zinc-200',
                  // Dark: Glass skeleton
                  'dark:bg-white/10'
                )}
              >
                <motion.div
                  initial={{ width: '0%' }}
                  animate={{
                    width: phase === 'verify' || phase === 'beacon' ? '100%' : '0%',
                  }}
                  transition={{
                    delay: 0.3 + 0.15 * i,
                    duration: 0.4,
                    ease: 'easeOut',
                  }}
                  className={cn(
                    'h-full rounded-full',
                    // Light: Fill with Black
                    'bg-zinc-900',
                    // Dark: Fill with Emerald + glow (per design system Section 8)
                    'dark:bg-emerald-500 dark:shadow-[0_0_10px_rgba(16,185,129,0.5)]'
                  )}
                />
              </motion.div>
            ))}
          </div>

          {/* 4. THE BEACON (Phase 4) */}
          <motion.div
            initial={{ scale: 0, opacity: 0 }}
            animate={{
              scale: phase === 'beacon' ? 1 : 0,
              opacity: phase === 'beacon' ? 1 : 0,
            }}
            transition={{
              type: 'spring',
              stiffness: 200,
              damping: 20,
            }}
            className={cn(
              'absolute bottom-20 z-10',
              'w-2 h-2 rounded-full',
              // Light: Solid Black Dot with subtle shadow (per Section 14)
              'bg-zinc-900 shadow-md ring-1 ring-black/5',
              // Dark: Glowing White Beacon (per Section 14)
              'dark:bg-white dark:ring-0',
              'dark:shadow-[0_0_15px_-3px_rgba(255,255,255,0.4)]'
            )}
          />

          {/* Safe area padding for mobile */}
          <div className="pb-safe" />
        </motion.div>
      )}
    </AnimatePresence>
  );
});

export default StartupSequence;
