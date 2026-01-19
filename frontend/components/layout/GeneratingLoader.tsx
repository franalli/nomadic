'use client';

import { motion } from 'framer-motion';
import { Briefcase, Bus, Car, CheckCircle2, Compass, Hotel, Mountain, Plane, Sparkles } from 'lucide-react';
import { memo, useEffect, useState } from 'react';

// Generation stages with estimated timing (1s per stage = 5s total)
const STAGES = [
  { label: 'Processing constraints', duration: 1000 },
  { label: 'Matching destinations', duration: 1000 },
  { label: 'Comparing options', duration: 1000 },
  { label: 'Loading activities', duration: 1000 },
  { label: 'Updating itinerary', duration: 1000 },
] as const;

// Particle indices for floating animation (extracted to avoid array recreation)
const PARTICLE_INDICES = [0, 1, 2, 3, 4, 5] as const;

// Shared transform for centering positioned elements
const CENTER_TRANSFORM = { transform: 'translate(-50%, -50%)' } as const;

interface GeneratingLoaderProps {
  /** Show compact version for mobile */
  compact?: boolean;
  /** Additional CSS classes */
  className?: string;
}

export const GeneratingLoader = memo(function GeneratingLoader({
  compact = false,
  className = '',
}: GeneratingLoaderProps) {
  const [currentStage, setCurrentStage] = useState(0);

  // Cycle through stages automatically
  useEffect(() => {
    if (currentStage >= STAGES.length) return;

    const timer = setTimeout(() => {
      setCurrentStage((prev) => Math.min(prev + 1, STAGES.length - 1));
    }, STAGES[currentStage].duration);

    return () => clearTimeout(timer);
  }, [currentStage]);

  // Compact version for mobile
  if (compact) {
    return (
      <div
        className={`flex w-full items-center justify-center py-8 ${className}`}
        role="status"
        aria-busy="true"
        aria-live="polite"
        aria-label="Updating plan, please wait"
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="flex flex-col items-center gap-4"
        >
          {/* Compact compass animation */}
          <div className="relative flex h-20 w-20 items-center justify-center">
            {/* Pulsing ring */}
            <div className="loader-pulse-ring absolute h-20 w-20 rounded-full border-2 border-primary/30" />

            {/* Center compass */}
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 8, repeat: Infinity, ease: 'linear' }}
              className="relative z-10 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-primary to-primary/80 shadow-xl"
            >
              <Compass className="h-7 w-7 text-primary-foreground" />
            </motion.div>
          </div>

          {/* Current stage text only */}
          <div className="flex flex-col items-center gap-2 text-center">
            <motion.p
              key={currentStage}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-sm font-medium text-primary"
            >
              {STAGES[currentStage].label}...
            </motion.p>

            {/* Compact progress bar */}
            <div className="h-1 w-32 overflow-hidden rounded-full bg-muted">
              <motion.div
                className="h-full w-1/3 bg-gradient-to-r from-primary to-accent"
                animate={{
                  x: ['-100%', '300%'],
                }}
                transition={{
                  duration: 1.5,
                  repeat: Infinity,
                  ease: 'easeInOut',
                }}
              />
            </div>
          </div>
        </motion.div>
      </div>
    );
  }

  // Full version for desktop
  return (
    <div
      className={`flex h-full min-h-[60vh] w-full items-center justify-center ${className}`}
      role="status"
      aria-busy="true"
      aria-live="polite"
      aria-label="Updating plan, please wait"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="flex flex-col items-center gap-8"
      >
        {/* Main loader animation */}
        <div className="relative flex h-48 w-48 items-center justify-center">
          {/* Outer glow ring */}
          <div className="loader-glow-ring absolute inset-0 rounded-full" />

          {/* Orbiting travel icons - Outer orbit (3 icons at 120° intervals) */}
          <div className="loader-orbit absolute inset-0">
            <Car className="absolute h-5 w-5 text-accent" style={{ left: '50%', top: '0%', ...CENTER_TRANSFORM }} />
            <Plane className="absolute h-5 w-5 text-primary" style={{ left: '93.3%', top: '75%', ...CENTER_TRANSFORM }} />
            <Mountain className="absolute h-5 w-5 text-accent/80" style={{ left: '6.7%', top: '75%', ...CENTER_TRANSFORM }} />
          </div>

          {/* Orbiting travel icons - Inner orbit (3 icons at 120° intervals, offset by 60°) */}
          <div className="loader-orbit-reverse absolute inset-[15%]">
            <Bus className="absolute h-4 w-4 text-primary/80" style={{ left: '75%', top: '6.7%', ...CENTER_TRANSFORM }} />
            <Hotel className="absolute h-4 w-4 text-accent/70" style={{ left: '75%', top: '93.3%', ...CENTER_TRANSFORM }} />
            <Briefcase className="absolute h-4 w-4 text-primary/70" style={{ left: '0%', top: '50%', ...CENTER_TRANSFORM }} />
          </div>

          {/* Inner pulsing rings */}
          <div className="loader-pulse-ring absolute h-32 w-32 rounded-full border-2 border-primary/30" />
          <div className="loader-pulse-ring-delayed absolute h-24 w-24 rounded-full border-2 border-accent/20" />

          {/* Center compass */}
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 8, repeat: Infinity, ease: 'linear' }}
            className="relative z-10 flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-primary to-primary/80 shadow-2xl"
          >
            <Compass className="h-10 w-10 text-primary-foreground" />
          </motion.div>

          {/* Floating particles */}
          {PARTICLE_INDICES.map((i) => (
            <motion.div
              key={i}
              className="loader-particle absolute h-2 w-2 rounded-full bg-accent/60"
              style={{
                left: `${50 + 40 * Math.cos((i * Math.PI * 2) / 6)}%`,
                top: `${50 + 40 * Math.sin((i * Math.PI * 2) / 6)}%`,
              }}
              animate={{
                scale: [1, 1.5, 1],
                opacity: [0.4, 0.8, 0.4],
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                delay: i * 0.3,
                ease: 'easeInOut',
              }}
            />
          ))}
        </div>

        {/* Text content */}
        <div className="flex flex-col items-center gap-4 text-center">
          <motion.h2
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="font-display text-2xl font-bold text-foreground"
          >
            Updating Plan
          </motion.h2>

          {/* Stage indicators */}
          <div className="flex flex-col gap-2 mt-2 text-sm">
            {STAGES.map((stage, i) => {
              const isCompleted = i < currentStage;
              const isActive = i === currentStage;

              return (
                <motion.div
                  key={stage.label}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{
                    opacity: isCompleted || isActive ? 1 : 0.4,
                    x: 0,
                  }}
                  transition={{ delay: i * 0.1, duration: 0.3 }}
                  className={`flex items-center gap-2 ${
                    isActive ? 'text-primary font-medium' :
                    isCompleted ? 'text-accent' : 'text-muted-foreground'
                  }`}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="h-4 w-4 text-accent shrink-0" />
                  ) : isActive ? (
                    <motion.div
                      animate={{ scale: [1, 1.2, 1] }}
                      transition={{ duration: 1, repeat: Infinity }}
                      className="h-4 w-4 rounded-full border-2 border-primary shrink-0"
                    />
                  ) : (
                    <div className="h-4 w-4 rounded-full border border-muted-foreground/30 shrink-0" />
                  )}
                  <span>{stage.label}</span>
                </motion.div>
              );
            })}
          </div>

          {/* Indeterminate progress bar */}
          <div className="mt-4 h-1.5 w-48 overflow-hidden rounded-full bg-muted">
            <motion.div
              className="h-full w-1/3 bg-gradient-to-r from-primary to-accent"
              animate={{
                x: ['-100%', '300%'],
              }}
              transition={{
                duration: 1.5,
                repeat: Infinity,
                ease: 'easeInOut',
              }}
            />
          </div>
        </div>

        {/* Decorative bottom sparkles */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="flex items-center gap-3 text-muted-foreground/50"
        >
          <Sparkles className="h-3 w-3" />
          <span className="text-xs font-medium uppercase tracking-wider">Updating plan</span>
          <Sparkles className="h-3 w-3" />
        </motion.div>
      </motion.div>
    </div>
  );
});
