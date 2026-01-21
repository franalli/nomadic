'use client';

import { AnimatePresence, motion } from 'framer-motion';
import Link from 'next/link';
import React, { memo } from 'react';

import { MobileModeHeader } from '@/components/layout/MobileModeHeader';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Animation Variants (per spec: 260ms slide, 240ms reverse)
// ─────────────────────────────────────────────────────────────────────────────

const mobileSlideVariants = {
  // Planner Mode (slide in from left)
  plannerEnter: { x: -12, opacity: 0.96 },
  plannerCenter: { x: 0, opacity: 1 },
  plannerExit: { x: -12, opacity: 0.96 },

  // Plan Mode (slide in from right)
  planEnter: { x: 12, opacity: 0.96 },
  planCenter: { x: 0, opacity: 1 },
  planExit: { x: 12, opacity: 0.96 },
};

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface SplitLayoutViewProps {
  /** Content for the left panel (Planner: TripDetailsForm + ChatPanel) */
  plannerContent: React.ReactNode;
  /** Content for the right panel (Plan View: StrategyStageRenderer) */
  planViewContent: React.ReactNode;
  /** Current plan state for status display */
  planState?: PlanState;
  /** Optional compact header content (branding) */
  headerContent?: React.ReactNode;
  /** Whether a destination has been set (controls topography background opacity) */
  hasDestination?: boolean;
  /** Callback to reset/clear the session */
  onReset?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * SplitLayoutView - Unified responsive layout for Nomadic.
 *
 * Desktop (lg+): True split view from the start
 * - Left: Planner panel (TripDetailsForm + ChatPanel), scrollable
 * - Right: Plan View (StrategyStageRenderer), always visible
 *
 * Mobile (<lg): Single surface with mode switching
 * - Planner Mode: Shows planner content only
 * - Plan Mode: Shows plan view only
 * - Animated transitions between modes
 */
export const SplitLayoutView = memo(function SplitLayoutView({
  plannerContent,
  planViewContent,
  planState = 'INCOMPLETE',
  headerContent,
  hasDestination: _hasDestination = false, // Reserved for future topo background control
  onReset,
}: SplitLayoutViewProps) {
  void _hasDestination; // Silence unused variable warning - reserved for future topo background control
  const { mode, isDesktop } = useMobileMode();

  return (
    <div className="flex flex-col min-h-screen pt-[calc(48px+env(safe-area-inset-top))] lg:pt-0">
      {/* Compact Header (branding) - always visible on desktop, mode-aware on mobile */}
      {headerContent && (
        <header className="hidden lg:flex items-center h-12 px-6 border-b border-[var(--theme-hairline)] bg-[var(--theme-panel)]">
          {headerContent}
        </header>
      )}

      {/* Mobile Mode Header - replaces header on mobile */}
      <MobileModeHeader planState={planState} onReset={onReset} />

      {/* Main Layout Container */}
      {/* Desktop: Grid 40/60 split | Mobile: Single column with mode switching */}
      <div
        className={cn(
          'flex-1 overflow-hidden',
          // Mobile: flex column for mode switching
          'flex flex-col',
          // Desktop: Grid with 40/60 split (min 360px, max 480px on ultrawide)
          'lg:grid lg:grid-cols-[minmax(360px,40%)_1fr]',
          '2xl:grid-cols-[480px_1fr]'
        )}
      >
        {/* ─────────────────────────────────────────────────────────────────── */}
        {/* Desktop Layout: True Split View (lg+) */}
        {/* ─────────────────────────────────────────────────────────────────── */}
        {isDesktop && (
          <>
            {/* Left Panel: Planner (40% or max 480px) */}
            <aside
              className={cn(
                'hidden lg:flex lg:flex-col',
                'h-[calc(100vh-48px)]', // Full height minus header
                'border-r border-[var(--theme-hairline)]',
                'bg-[var(--theme-panel)]',
                // Enhanced multi-layer shadow for better panel separation
                'shadow-[4px_0_12px_rgba(0,0,0,0.06),8px_0_24px_rgba(0,0,0,0.04)]'
              )}
              style={{ position: 'relative', zIndex: 1 }}
              aria-label="Trip planner"
            >
              <div className="flex-1 overflow-y-auto no-scrollbar p-5">
                {plannerContent}
              </div>
              {/* Desktop footer - pinned at bottom of left rail */}
              <footer className="shrink-0 flex items-center justify-center gap-3 px-5 py-3 border-t border-[var(--theme-hairline)] text-[11px] text-[var(--theme-link-muted)]">
                <Link href="/privacy" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Privacy</Link>
                <span aria-hidden="true" className="opacity-30">·</span>
                <Link href="/terms" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Terms</Link>
                <span aria-hidden="true" className="opacity-30">·</span>
                <Link href="/cookies" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Cookies</Link>
                <span aria-hidden="true" className="opacity-30">·</span>
                <Link href="/contact" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Contact</Link>
              </footer>
            </aside>

            {/* Right Panel: Plan View (60% or remaining space) */}
            <main
              className={cn(
                'hidden lg:flex lg:flex-col',
                'h-[calc(100vh-48px)]',
                'rightCanvas' // topo background via pseudo-elements
              )}
              aria-label="Your trip plan"
              data-testid="plan-view"
            >
              <div className="flex-1 overflow-y-auto no-scrollbar p-6">
                {planViewContent}
              </div>
            </main>
          </>
        )}

        {/* ─────────────────────────────────────────────────────────────────── */}
        {/* Mobile Layout: Mode Switching (<lg) */}
        {/* ─────────────────────────────────────────────────────────────────── */}
        {!isDesktop && (
          <AnimatePresence mode="wait">
            {mode === 'planner' ? (
              <motion.main
                key="mobile-planner"
                className="flex-1 overflow-y-auto p-4 lg:hidden bg-[var(--theme-panel)]"
                initial="plannerEnter"
                animate="plannerCenter"
                exit="plannerExit"
                variants={mobileSlideVariants}
                transition={{ duration: 0.24, ease: 'easeOut' }}
                aria-label="Trip planner"
              >
                {plannerContent}
              </motion.main>
            ) : (
              <motion.main
                key="mobile-plan"
                className="flex-1 overflow-y-auto p-4 lg:hidden rightCanvas"
                initial="planEnter"
                animate="planCenter"
                exit="planExit"
                variants={mobileSlideVariants}
                transition={{ duration: 0.26, ease: 'easeOut' }}
                aria-label="Your trip plan"
                data-testid="plan-view"
              >
                {planViewContent}
              </motion.main>
            )}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
});
