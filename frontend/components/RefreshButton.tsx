/**
 * RefreshButton
 *
 * High-contrast badge button that appears when trip inputs have changed.
 * Positioned above map controls for optimal visibility.
 * Uses portal to render to document.body, escaping any container constraints.
 *
 * @see docs/design-system.md - DS.actions.primary
 */

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/utils';

interface RefreshButtonProps {
  /** Whether trip inputs have changed since last regeneration */
  hasChanges: boolean;
  /** Whether regeneration is in progress */
  isRefreshing: boolean;
  /** Callback when button is clicked */
  onClick: () => void;
}

export function RefreshButton({ hasChanges, isRefreshing, onClick }: RefreshButtonProps) {
  // Track if we're mounted (needed for portal)
  const [mounted, setMounted] = useState(false);

  // Wrap onClick to add logging
  const handleClick = () => {
    console.log('[RefreshButton] 🖱️ Click detected', { hasChanges, isRefreshing });
    onClick();
  };

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  // Show when: has changes OR currently refreshing
  // Hide when: no changes AND not refreshing (plan is current)
  const shouldShow = hasChanges || isRefreshing;

  // Don't render until mounted (SSR safety)
  if (!mounted) return null;

  // Don't render if nothing to show
  if (!shouldShow) return null;

  return createPortal(
    <AnimatePresence>
      {shouldShow && (
        <motion.button
          initial={{ scale: 0, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0, opacity: 0, y: 20 }}
          transition={{ type: 'spring', stiffness: 400, damping: 25 }}
          onClick={handleClick}
          disabled={isRefreshing || !hasChanges}
          aria-label={isRefreshing ? 'Refreshing plan...' : 'Refresh plan'}
          className={cn(
            // Position: Fixed above map controls (z-50 above map at z-40)
            'fixed bottom-24 right-6 z-50',
            // Size: Pill badge shape
            'min-w-[160px] h-14 px-6 rounded-full',
            // Layout
            'flex items-center justify-center gap-2',
            // Typography
            'font-bold text-sm',
            // Transitions
            'transition-all duration-200',
            // Interaction
            'hover:scale-105 active:scale-95',
            'disabled:cursor-not-allowed disabled:hover:scale-100',

            // Active state (has changes, ready to refresh)
            hasChanges &&
              !isRefreshing && [
                // Amber gradient - high contrast against emerald brand
                'bg-gradient-to-r from-amber-500 to-orange-500',
                'text-white',
                // Strong shadow for visibility
                'shadow-2xl shadow-amber-500/50',
                // Pulsing animation to draw attention
                'animate-pulse',
              ],

            // Refreshing state
            isRefreshing && [
              'bg-zinc-200 text-zinc-600',
              'dark:bg-zinc-800 dark:text-zinc-400',
              'cursor-wait',
              'shadow-lg',
              'animate-none', // Stop pulse when refreshing
            ]
          )}
        >
          {isRefreshing ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              <span>REFRESHING...</span>
            </>
          ) : (
            <>
              <RefreshCw className="w-5 h-5" />
              <span>REFRESH PLAN</span>
            </>
          )}
        </motion.button>
      )}
    </AnimatePresence>,
    document.body
  );
}
