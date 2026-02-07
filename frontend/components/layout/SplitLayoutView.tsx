'use client';

import Link from 'next/link';
import React, { memo } from 'react';

import { MobileModeHeader } from '@/components/layout/MobileModeHeader';
import { MobileSwipeLayout } from '@/components/layout/MobileSwipeLayout';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

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
  /** Mobile-only: chat input rendered below swipe container (visible on both pages) */
  mobileInput?: React.ReactNode;
  /** Mobile-only: trip status bar rendered above swipe container (shared across pages) */
  mobileStatusBar?: React.ReactNode;
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
 * Mobile (<lg): Horizontal swipe layout (Chat ↔ Plan)
 * - CSS scroll-snap with two full-screen pages
 * - Tab bar for tap navigation + badge indicator
 * - Auto-navigates to plan when content arrives
 */
export const SplitLayoutView = memo(function SplitLayoutView({
  plannerContent,
  planViewContent,
  bookContent: _bookContent,
  planState = 'INCOMPLETE',
  headerContent,
  hasDestination: _hasDestination = false,
  onReset,
  onSendMessage: _onSendMessage,
  isProcessing: _isProcessing = false,
  planTabEnabled = false,
  bookTabEnabled: _bookTabEnabled = false,
  onSelectDates: _onSelectDates,
  mobileInput,
  mobileStatusBar,
}: SplitLayoutViewProps) {
  void _hasDestination; // Reserved for future topo background control
  void _bookTabEnabled; // Kept for API compat
  void _onSendMessage; // Kept for API compat
  void _isProcessing; // Kept for API compat
  void _onSelectDates; // Kept for API compat
  void _bookContent; // Kept for API compat
  const isDesktop = useIsDesktop();

  return (
    <div className="flex flex-col h-[100dvh] lg:h-screen overflow-hidden">
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
      {/* Desktop: Grid 40/60 split | Mobile: Horizontal swipe pages */}
      <div
        className={cn(
          'flex-1 overflow-hidden min-h-0', // min-h-0 fixes flexbox height collapse on mobile
          // Mobile: flex column for swipe layout
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
              <div id="plan-panel" className="flex-1 overflow-y-auto no-scrollbar px-6 pb-6 pt-0">
                {planViewContent}
              </div>
            </main>
          </>
        )}

        {/* ─────────────────────────────────────────────────────────────────── */}
        {/* Mobile Layout: Horizontal Swipe (Chat ↔ Plan) */}
        {/* ─────────────────────────────────────────────────────────────────── */}
        {!isDesktop && (
          <main
            className={cn(
              'flex-1 flex flex-col overflow-hidden min-h-0 lg:hidden',
              'pt-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]',
            )}
          >
            {/* Shared TripStatusBar — visible on both Chat and Plan pages */}
            {mobileStatusBar}

            <MobileSwipeLayout
              chatContent={plannerContent}
              planContent={planViewContent}
              planTabEnabled={planTabEnabled}
            />

            {/* Shared chat input — visible on both Chat and Plan pages */}
            {mobileInput}
          </main>
        )}
      </div>
    </div>
  );
});
