/**
 * RefreshButton
 *
 * High-contrast badge button that appears when trip inputs have changed.
 * Supports two variants:
 * - floating: Fixed position above map controls (uses portal)
 * - inline: Rendered inline at end of chip bar (no portal)
 *
 * @see docs/design-system.md - DS.actions.primary
 */

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, RefreshCw, RotateCw } from 'lucide-react';
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
  /** Rendering variant - floating FAB or inline pill */
  variant?: 'floating' | 'inline';
}

export function RefreshButton({ hasChanges, isRefreshing, onClick, variant = 'floating' }: RefreshButtonProps) {
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

  // Don't render if nothing to show
  if (!shouldShow) return null;

  // Inline variant: rendered directly in chip bar (no portal, no SSR check needed)
  if (variant === 'inline') {
    return (
      <button
        onClick={handleClick}
        disabled={isRefreshing}
        className={cn(
          'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
          'text-xs font-medium shadow-md',
          'transition-all duration-200',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          'animate-in fade-in slide-in-from-right-2 duration-200',
          // Active state
          hasChanges &&
            !isRefreshing && [
              'bg-gradient-to-r from-amber-500 to-orange-500',
              'text-white',
              'hover:from-amber-600 hover:to-orange-600',
            ],
          // Refreshing state
          isRefreshing && [
            'bg-zinc-200 text-zinc-600',
            'dark:bg-zinc-800 dark:text-zinc-400',
            'cursor-wait',
          ]
        )}
      >
        {isRefreshing ? (
          <>
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>Refreshing...</span>
          </>
        ) : (
          <>
            <RotateCw className="w-3 h-3" />
            <span>Refresh</span>
          </>
        )}
      </button>
    );
  }

  // Don't render floating variant until mounted (SSR safety)
  if (!mounted) return null;

  // Floating variant: fixed position with portal
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
