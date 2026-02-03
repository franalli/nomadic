/**
 * RefreshOverlay
 *
 * Full-screen overlay displayed when refreshing the plan.
 * Locks interaction and shows a design-system compliant loader.
 *
 * @see docs/design-system.md - Section 22: Loading States
 */

'use client';

import { Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';

interface RefreshOverlayProps {
  /** Whether the overlay is visible */
  isRefreshing: boolean;
}

export function RefreshOverlay({ isRefreshing }: RefreshOverlayProps) {
  if (!isRefreshing) return null;

  return (
    <div
      className={cn(
        'fixed inset-0 z-50 flex items-center justify-center',
        // Light: Soft white overlay
        'bg-white/80 backdrop-blur-xl',
        // Dark: Deep glass ("Bioluminescent Depth")
        'dark:bg-zinc-950/90 dark:backdrop-blur-xl'
      )}
    >
      {/* Glass Card Container */}
      <div
        className={cn(
          'flex flex-col items-center gap-6 p-8 rounded-2xl',
          // Light: Glass surface
          'bg-white/90 border border-zinc-200 shadow-xl shadow-zinc-200/50',
          // Dark: Glass surface with emerald glow
          'dark:bg-zinc-900/80 dark:border-white/10',
          'dark:shadow-[0_0_40px_-10px_rgba(16,185,129,0.3)]'
        )}
      >
        {/* Large Emerald Spinner */}
        <Loader2
          className={cn(
            'w-16 h-16 animate-spin',
            // Light: Solid black
            'text-zinc-900',
            // Dark: Emerald with glow
            'dark:text-emerald-500',
            'dark:drop-shadow-[0_0_15px_rgba(16,185,129,0.5)]'
          )}
        />

        {/* Status Text */}
        <div className="text-center">
          <p className={cn('text-lg font-semibold', 'text-zinc-900 dark:text-white')}>
            Refreshing your plan...
          </p>
          <p className={cn('text-sm mt-1', 'text-zinc-500 dark:text-zinc-400')}>
            This may take a few seconds
          </p>
        </div>
      </div>
    </div>
  );
}
