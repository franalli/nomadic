'use client';

import { AnimatePresence, motion } from 'framer-motion';
import Link from 'next/link';
import React, { memo } from 'react';

import { MobileModeHeader } from '@/components/layout/MobileModeHeader';
import { MobilePlanFooter } from '@/components/layout/MobilePlanFooter';
import { MobileTabBar } from '@/components/layout/MobileTabBar';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Animation Variants (per spec: 260ms slide, 240ms reverse)
// ─────────────────────────────────────────────────────────────────────────────

const mobileSlideVariants = {
  // Chat tab (leftmost - slide in from left)
  chatEnter: { x: -12, opacity: 0.96 },
  chatCenter: { x: 0, opacity: 1 },
  chatExit: { x: -12, opacity: 0.96 },

  // Plan tab (center - slide in from right for chat, left for book)
  planEnter: { x: 12, opacity: 0.96 },
  planCenter: { x: 0, opacity: 1 },
  planExit: { x: 12, opacity: 0.96 },

  // Book tab (rightmost - slide in from right)
  bookEnter: { x: 12, opacity: 0.96 },
  bookCenter: { x: 0, opacity: 1 },
  bookExit: { x: 12, opacity: 0.96 },
};

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface SplitLayoutViewProps {
  /** Content for the left panel (Planner: TripDetailsForm + ChatPanel) */
  plannerContent: React.ReactNode;
  /** Content for the right panel (Plan View: StrategyStageRenderer) */
  planViewContent: React.ReactNode;
  /** Content for the Book tab (BookingSection) */
  bookContent?: React.ReactNode;
  /** Current plan state for status display */
  planState?: PlanState;
  /** Whether we're in the setup phase (S0_BOOTSTRAP) */
  isSetupPhase?: boolean;
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
  /** Whether the Book tab has content and should be enabled */
  bookTabEnabled?: boolean;
  /** Whether dates have been set (determines CTA button type) */
  hasDates?: boolean;
  /** Whether to show the CTA button in the footer */
  showCta?: boolean;
  /** Handler for "Create Itinerary" CTA button */
  onBuildItinerary?: () => void;
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
 * Mobile (<lg): Single surface with mode switching
 * - Planner Mode: Shows planner content only
 * - Plan Mode: Shows plan view only
 * - Animated transitions between modes
 */
export const SplitLayoutView = memo(function SplitLayoutView({
  plannerContent,
  planViewContent,
  bookContent,
  planState = 'INCOMPLETE',
  isSetupPhase = false,
  headerContent,
  hasDestination: _hasDestination = false, // Reserved for future topo background control
  onReset,
  onSendMessage,
  isProcessing = false,
  bookTabEnabled = true,
  hasDates = false,
  showCta = false,
  onBuildItinerary,
  onSelectDates,
}: SplitLayoutViewProps) {
  void _hasDestination; // Silence unused variable warning - reserved for future topo background control
  const { activeTab, isDesktop } = useMobileMode();

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
        isSetupPhase={isSetupPhase}
        onReset={onReset}
      />

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
        {/* Mobile Layout: 3-Tab Switching (<lg) */}
        {/* ─────────────────────────────────────────────────────────────────── */}
        {!isDesktop && (
          <>
            <AnimatePresence mode="wait">
              {activeTab === 'chat' && (
                <motion.main
                  key="mobile-chat"
                  className={cn(
                    'flex-1 overflow-y-auto p-4 lg:hidden bg-[var(--theme-panel)]',
                    'pt-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]', // Space for fixed header
                    'pb-[calc(var(--mobile-tab-bar-height,68px)+env(safe-area-inset-bottom))]' // Space for tab bar
                  )}
                  initial="chatEnter"
                  animate="chatCenter"
                  exit="chatExit"
                  variants={mobileSlideVariants}
                  transition={{ duration: 0.24, ease: 'easeOut' }}
                  aria-label="Trip planner"
                >
                  {plannerContent}
                </motion.main>
              )}

              {activeTab === 'plan' && (
                <motion.main
                  key="mobile-plan"
                  id="plan-panel"
                  className={cn(
                    'flex-1 overflow-y-auto p-4 lg:hidden rightCanvas',
                    'pt-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]', // Space for fixed header
                    'pb-[200px]' // Space for MobilePlanFooter (CTA + input + tab bar)
                  )}
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

              {activeTab === 'book' && (
                <motion.main
                  key="mobile-book"
                  className={cn(
                    'flex-1 overflow-y-auto p-4 lg:hidden rightCanvas',
                    'pt-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]', // Space for fixed header
                    'pb-[200px]' // Space for MobilePlanFooter (input + tab bar)
                  )}
                  initial="bookEnter"
                  animate="bookCenter"
                  exit="bookExit"
                  variants={mobileSlideVariants}
                  transition={{ duration: 0.26, ease: 'easeOut' }}
                  aria-label="Booking options"
                >
                  {bookContent}
                </motion.main>
              )}
            </AnimatePresence>

            {/* Mobile Plan Footer - CTA + Input, visible on Plan/Book tabs */}
            {onSendMessage && (
              <MobilePlanFooter
                hasDates={hasDates}
                showCta={showCta}
                onBuildItinerary={onBuildItinerary ?? (() => {})}
                onSelectDates={onSelectDates ?? (() => {})}
                onSendMessage={onSendMessage}
                isProcessing={isProcessing}
              />
            )}

            {/* Mobile Tab Bar */}
            <MobileTabBar bookTabEnabled={bookTabEnabled} />
          </>
        )}
      </div>
    </div>
  );
});
