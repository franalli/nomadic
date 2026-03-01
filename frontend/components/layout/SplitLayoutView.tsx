'use client';

import Link from 'next/link';
import React from 'react';

import { MobileModeHeader } from '@/components/layout/MobileModeHeader';
import { MobileSwipeLayout } from '@/components/layout/MobileSwipeLayout';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface SplitLayoutViewProps {
  /** Content for the left panel (Planner: chat + controls) */
  plannerContent: React.ReactNode;
  /** Content for the right panel (Plan View: StrategyStageRenderer) */
  planViewContent: React.ReactNode;
  /** Current plan state for status display */
  planState?: PlanState;
  /** Optional compact header content (branding) */
  headerContent?: React.ReactNode;
  /** Callback to reset/clear the session */
  onReset?: () => void;
  /** Whether a reset request is currently in-flight */
  isResetting?: boolean;
  /** Whether Plan tab is unlocked (plan has been generated) */
  planTabEnabled?: boolean;
  /** Mobile-only: chat input rendered below swipe container (visible on both pages) */
  mobileInput?: React.ReactNode;
  /** Mobile-only: trip status bar rendered above swipe container (shared across pages) */
  mobileStatusBar?: React.ReactNode;
  /** Data density from StrategyStageRenderer — controls landing vs plan-active layout */
  dataDensity?: 'empty' | 'ghost' | 'bridge' | 'full';
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * SplitLayoutView - Unified responsive layout for Nomadic.
 *
 * Desktop (lg+): True split view from the start
 * - Left: Planner panel (chat + controls), scrollable
 * - Right: Plan View (StrategyStageRenderer), always visible
 *
 * Mobile (<lg): Horizontal swipe layout (Chat ↔ Plan)
 * - CSS scroll-snap with two full-screen pages
 * - Tab bar for tap navigation + badge indicator
 * - Auto-navigates to plan when content arrives
 *
 * Landing→Split transition uses pure CSS transitions (compositor thread, no layout thrash).
 */
export function SplitLayoutView({
  plannerContent,
  planViewContent,
  planState = 'INCOMPLETE',
  headerContent,
  onReset,
  isResetting = false,
  planTabEnabled = false,
  mobileInput,
  mobileStatusBar,
  dataDensity = 'empty',
}: SplitLayoutViewProps) {
  const isDesktop = useIsDesktop();

  const isLanding = dataDensity === 'empty' || dataDensity === 'bridge' || dataDensity === 'ghost';

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
        isResetting={isResetting}
      />

      {/* Main Layout Container */}
      {/* Desktop: Flex row (relative for topo overlay) | Mobile: Horizontal swipe pages */}
      <div
        className={cn(
          'flex-1 overflow-hidden min-h-0', // min-h-0 fixes flexbox height collapse on mobile
          // Mobile: flex column for swipe layout
          'flex flex-col',
          // Desktop: flex row with relative positioning for topo background
          'lg:flex lg:flex-row lg:relative'
        )}
      >
        {/* ─────────────────────────────────────────────────────────────────── */}
        {/* Desktop Layout: Adaptive Split View (lg+) */}
        {/* ─────────────────────────────────────────────────────────────────── */}
        {isDesktop && (
          <>
            {/* Topo background — CSS opacity transition, lingers longest (700ms) */}
            <div
              className={cn(
                'absolute inset-0 pointer-events-none z-0 bg-white dark:bg-zinc-950',
                'transition-opacity duration-700 ease-out',
                isLanding ? 'opacity-100' : 'opacity-0',
              )}
            >
              <div className="absolute inset-0 animate-topo-drift topo-contour-mask-350 opacity-[0.15] dark:opacity-[0.10]">
                <div className="absolute inset-0 bg-black dark:bg-white" />
              </div>
            </div>

            {/* Chat column — CSS width + margin transition (500ms ease-out) */}
            <aside
              className={cn(
                'relative z-10 flex flex-col',
                'h-[calc(100vh-48px)]',
                'transition-all duration-500 ease-[cubic-bezier(0.25,0.1,0.25,1)]',
                isLanding
                  ? 'w-[640px] mx-auto'
                  : [
                      'w-[480px] mx-0 shrink-0',
                      'border-r',
                      'bg-white border-zinc-200',
                      'shadow-[4px_0_24px_-12px_rgba(0,0,0,0.12),8px_0_40px_-20px_rgba(0,0,0,0.08)]',
                      'dark:bg-black/40 dark:backdrop-blur-xl dark:border-white/5',
                      'dark:shadow-[4px_0_12px_rgba(0,0,0,0.3)]',
                    ],
              )}
              aria-label="Trip planner"
            >
              {isLanding ? (
                /* Landing: optical center via top padding, footer pinned to bottom */
                <>
                  <div className="flex-1 flex flex-col overflow-y-auto no-scrollbar px-4">
                    {plannerContent}
                  </div>
                  <footer className={`shrink-0 flex items-center justify-center gap-2 px-4 py-3 ${DS.textSize.mini} text-[var(--theme-link-muted)]`}>
                    <Link href="/privacy" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Privacy</Link>
                    <span aria-hidden="true" className="opacity-30">·</span>
                    <Link href="/terms" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Terms</Link>
                    <span aria-hidden="true" className="opacity-30">·</span>
                    <Link href="/cookies" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Cookies</Link>
                    <span aria-hidden="true" className="opacity-30">·</span>
                    <Link href="/contact" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Contact</Link>
                  </footer>
                </>
              ) : (
                <>
                  <div className="flex-1 overflow-y-auto no-scrollbar p-4">
                    {plannerContent}
                  </div>
                  {/* Desktop footer - pinned at bottom of left rail */}
                  <footer className={`shrink-0 flex items-center justify-center gap-2 px-4 py-2 border-t border-[var(--theme-hairline)] ${DS.textSize.mini} text-[var(--theme-link-muted)]`}>
                    <Link href="/privacy" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Privacy</Link>
                    <span aria-hidden="true" className="opacity-30">·</span>
                    <Link href="/terms" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Terms</Link>
                    <span aria-hidden="true" className="opacity-30">·</span>
                    <Link href="/cookies" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Cookies</Link>
                    <span aria-hidden="true" className="opacity-30">·</span>
                    <Link href="/contact" className="hover:text-[var(--theme-link-muted-hover)] transition-colors">Contact</Link>
                  </footer>
                </>
              )}
            </aside>

            {/* Plan panel — always rendered, CSS transform + opacity transition (500ms, 100ms delay) */}
            <main
              className={cn(
                'flex flex-col',
                'h-[calc(100vh-48px)]',
                'rightCanvas',
                'transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] delay-100',
                isLanding
                  ? 'w-0 min-w-0 opacity-0 overflow-hidden pointer-events-none'
                  : 'flex-1 min-w-0 opacity-100',
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
}
