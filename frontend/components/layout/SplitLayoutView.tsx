'use client';

import { AnimatePresence, motion } from 'framer-motion';
import Link from 'next/link';
import React, { memo } from 'react';

import { MobileModeHeader } from '@/components/layout/MobileModeHeader';
import { MobilePlanFooter } from '@/components/layout/MobilePlanFooter';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Animation Variants
// ─────────────────────────────────────────────────────────────────────────────

const mobileSlideVariants = {
  // Planner mode (slide in from left)
  plannerEnter: { x: -12, opacity: 0.96 },
  plannerCenter: { x: 0, opacity: 1 },
  plannerExit: { x: -12, opacity: 0.96 },

  // Plan mode (slide in from right)
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
  /** Content for the Book tab (BookingSection) - rendered in plan view on mobile */
  bookContent?: React.ReactNode;
  /** Current plan state for status display */
  planState?: PlanState;
  /** Optional compact header content (branding) */
  headerContent?: React.ReactNode;
  /** Whether a destination has been set (controls topography background opacity) */
  hasDestination?: boolean;
  /** Callback to reset/clear the session */
  onReset?: () => void;
  /** Callback when user sends message from minimized input */
  onSendMessage?: (message: string) => void;
  /** Whether message is being processed (for minimized input) */
  isProcessing?: boolean;
  /** Whether Plan tab is unlocked (plan has been generated) - kept for API compat */
  planTabEnabled?: boolean;
  /** Whether the Book tab has content - kept for API compat */
  bookTabEnabled?: boolean;
  /** Handler for "Select Dates" CTA button */
  onSelectDates?: () => void;
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
 * Mobile (<lg): Two-mode switching (no tabs)
 * - Planner Mode: Shows planner content only
 * - Plan Mode: Shows plan view with single-scroll progressive disclosure
 * - Animated transitions between modes
 */
export const SplitLayoutView = memo(function SplitLayoutView({
  plannerContent,
  planViewContent,
  bookContent,
  planState = 'INCOMPLETE',
  headerContent,
  hasDestination: _hasDestination = false,
  onReset,
  onSendMessage,
  isProcessing = false,
  planTabEnabled: _planTabEnabled = false,
  bookTabEnabled: _bookTabEnabled = false,
  onSelectDates,
}: SplitLayoutViewProps) {
  void _hasDestination; // Reserved for future topo background control
  void _planTabEnabled; // Kept for API compat - tabs removed
  void _bookTabEnabled; // Kept for API compat - tabs removed
  const { mode, isDesktop } = useMobileMode();

  return (
    <div className="flex flex-col min-h-[100dvh] lg:min-h-screen lg:pt-0">
      {/* Compact Header (branding) - always visible on desktop, mode-aware on mobile */}
      {headerContent && (
        <header className="hidden lg:flex items-center h-12 px-6 border-b border-[var(--theme-hairline)] bg-[var(--theme-panel)]">
          {headerContent}
        </header>
      )}

      {/* Mobile Mode Header - replaces header on mobile */}
      <MobileModeHeader
        planState={planState}
        onReset={onReset}
      />

      {/* Main Layout Container */}
      {/* Desktop: Grid 40/60 split | Mobile: Single column with mode switching */}
      <div
        className={cn(
          'flex-1 overflow-hidden min-h-0', // min-h-0 fixes flexbox height collapse on mobile
          // Mobile: flex column for mode switching
          'flex flex-col',
          // Desktop: Grid with fluid chat panel width (clamp for continuous scaling)
          'lg:grid lg:grid-cols-[clamp(320px,28vw,480px)_1fr]'
        )}
      >
        {/* ─────────────────────────────────────────────────────────────────── */}
        {/* Desktop Layout: True Split View (lg+) */}
        {/* ─────────────────────────────────────────────────────────────────── */}
        {isDesktop && (
          <>
            {/* Left Panel: Planner (40% or max 480px) */}
            {/* Light Mode: Solid white cardstock with prominent shadow */}
            {/* Dark Mode: Subtle tinted glass */}
            <aside
              className={cn(
                'hidden lg:flex lg:flex-col',
                'h-[calc(100vh-48px)]', // Full height minus header
                'border-r',
                // Light: white cardstock with sharp border
                'bg-white border-zinc-200',
                // Light: prominent shadow for "floating paper" effect
                'shadow-[4px_0_24px_-12px_rgba(0,0,0,0.12),8px_0_40px_-20px_rgba(0,0,0,0.08)]',
                // Dark: tinted glass with subtle border
                'dark:bg-black/40 dark:backdrop-blur-xl dark:border-white/5',
                'dark:shadow-[4px_0_12px_rgba(0,0,0,0.3)]'
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
              <div id="plan-panel" className="flex-1 overflow-y-auto no-scrollbar p-6">
                {planViewContent}
              </div>
            </main>
          </>
        )}

        {/* ─────────────────────────────────────────────────────────────────── */}
        {/* Mobile Layout: Two-Mode Switching (<lg) - No Tabs */}
        {/* ─────────────────────────────────────────────────────────────────── */}
        {!isDesktop && (
          <>
            <AnimatePresence mode="wait">
              {mode === 'planner' && (
                <motion.main
                  key="mobile-planner"
                  className={cn(
                    'flex-1 overflow-y-auto p-4 lg:hidden bg-[var(--theme-panel)]',
                    'pt-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]', // Space for fixed header
                    'pb-[calc(env(safe-area-inset-bottom)+16px)]' // Safe area + breathing room
                  )}
                  initial="plannerEnter"
                  animate="plannerCenter"
                  exit="plannerExit"
                  variants={mobileSlideVariants}
                  transition={{ duration: 0.24, ease: 'easeOut' }}
                  aria-label="Trip planner"
                >
                  {plannerContent}
                </motion.main>
              )}

              {mode === 'plan' && (
                <motion.main
                  key="mobile-plan"
                  id="plan-panel"
                  className={cn(
                    // Single-scroll container for progressive disclosure
                    'flex-1 h-full min-h-0 lg:hidden rightCanvas overflow-y-auto',
                    'pt-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]', // Space for fixed header
                    'pb-[calc(env(safe-area-inset-bottom)+140px)]' // Space for MobilePlanFooter
                  )}
                  initial="planEnter"
                  animate="planCenter"
                  exit="planExit"
                  variants={mobileSlideVariants}
                  transition={{ duration: 0.26, ease: 'easeOut' }}
                  aria-label="Your trip plan"
                  data-testid="plan-view"
                >
                  {/* Single-scroll progressive disclosure: plan content + booking */}
                  <div className="flex flex-col gap-6">
                    {planViewContent}
                    {/* Booking section integrated into single scroll */}
                    {bookContent && (
                      <section className="px-4 pb-4" aria-label="Booking options">
                        {bookContent}
                      </section>
                    )}
                  </div>
                </motion.main>
              )}
            </AnimatePresence>

            {/* Mobile Plan Footer - Command input, visible in plan mode */}
            {onSendMessage && (
              <MobilePlanFooter
                onSelectDates={onSelectDates ?? (() => {})}
                onSendMessage={onSendMessage}
                isProcessing={isProcessing}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
});
