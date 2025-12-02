'use client';

import { motion } from 'framer-motion';
import { Compass, Sparkles } from 'lucide-react';

interface GeneratingLoaderProps {
  /** Progress value from 0 to 1, or undefined for indeterminate */
  progress?: number;
}

export function GeneratingLoader({ progress }: GeneratingLoaderProps) {
  // Inspirational messages that cycle during generation
  const messages = [
    'Crafting your perfect itinerary...',
    'Exploring hidden gems...',
    'Comparing the best options...',
    'Personalizing your adventure...',
    'Almost there...',
  ];

  return (
    <div className="flex h-full min-h-[60vh] w-full items-center justify-center">
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

          {/* Orbiting sparkles */}
          <div className="loader-orbit absolute inset-0">
            <Sparkles className="absolute left-1/2 top-0 h-5 w-5 -translate-x-1/2 -translate-y-1/2 text-accent" />
          </div>
          <div className="loader-orbit-delayed absolute inset-0">
            <Sparkles className="absolute bottom-0 left-1/2 h-4 w-4 -translate-x-1/2 translate-y-1/2 text-primary" />
          </div>
          <div className="loader-orbit-slow absolute inset-0">
            <Sparkles className="absolute left-0 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 text-accent/80" />
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
          {[...Array(6)].map((_, i) => (
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
            Creating Your Trip Options
          </motion.h2>

          {/* Cycling message */}
          <div className="h-6 overflow-hidden">
            <motion.div
              animate={{
                y: [0, -24, -48, -72, -96],
              }}
              transition={{
                duration: 12.5,
                repeat: Infinity,
                ease: 'linear',
                times: [0, 0.2, 0.4, 0.6, 0.8],
                repeatDelay: 0,
              }}
              className="text-muted-foreground text-sm"
            >
              {messages.map((msg, i) => (
                <span key={i} className="block h-6 leading-6">
                  {msg}
                </span>
              ))}
            </motion.div>
          </div>

          {/* Progress bar (if progress is provided) */}
          {progress !== undefined && (
            <div className="mt-2 h-1.5 w-48 overflow-hidden rounded-full bg-muted">
              <motion.div
                className="h-full bg-gradient-to-r from-primary to-accent"
                initial={{ width: 0 }}
                animate={{ width: `${progress * 100}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
          )}

          {/* Indeterminate progress bar */}
          {progress === undefined && (
            <div className="mt-2 h-1.5 w-48 overflow-hidden rounded-full bg-muted">
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
          )}
        </div>

        {/* Decorative bottom sparkles */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="flex items-center gap-3 text-muted-foreground/50"
        >
          <Sparkles className="h-3 w-3" />
          <span className="text-xs font-medium uppercase tracking-wider">AI-Powered Planning</span>
          <Sparkles className="h-3 w-3" />
        </motion.div>
      </motion.div>
    </div>
  );
}
