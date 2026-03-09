'use client';

import {
  Check,
  Compass,
  Loader2,
  MoreVertical,
  SlidersHorizontal,
} from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { MobileHeaderMenu } from '@/components/layout/MobileHeaderMenu';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useHeaderActions } from '@/hooks/useHeaderActions';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import { useUIStore } from '@/state/uiStore';
import { useUserStore } from '@/state/userStore';
import type { PlanState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MobileModeHeaderProps {
  /** Current plan state for status display in Plan Mode */
  planState?: PlanState;
  /** Callback to reset/clear the session */
  onReset?: () => void;
  /** Whether reset is currently in-flight (guards against spamming) */
  isResetting?: boolean;
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Status Configuration
// ─────────────────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  PlanState,
  { text: string; icon?: React.ReactNode; className: string }
> = {
  INCOMPLETE: {
    text: '',
    className: 'text-muted-foreground',
  },
  RESOLVING: {
    text: 'Planning...',
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    className: 'text-primary/80',
  },
  STABLE: {
    text: '',
    icon: <Check className="h-3 w-3" />,
    className: 'text-emerald-600/80 dark:text-emerald-400/80',
  },
  LOCKED: {
    text: 'Locked',
    className: 'text-foreground',
  },
};

const MOBILE_PLAN_SCROLL_TO_TOP_EVENT = 'nomadic:mobile-plan-scroll-top';

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * MobileModeHeader - Mobile-only header with consistent branding.
 *
 * DESIGN PRINCIPLE: Bottom tabs are the ONLY navigation method.
 * No "<- Edit" back button - this creates a parallel workspace model
 * like Instagram, Airbnb, or Spotify where you tap tabs to switch views.
 *
 * Both Modes:
 * - Left: Nomadic logo + wordmark (brand anchor)
 * - Right: Menu (three dots) with Reset, Help & Legal
 *
 * Plan Mode additionally shows status indicator.
 */
function MobileModeHeaderInner({
  planState = 'INCOMPLETE',
  onReset,
  isResetting = false,
  className,
}: MobileModeHeaderProps) {
  const isDesktop = useIsDesktop();
  const [menuOpen, setMenuOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const activePage = useMobileNavStore((s) => s.activePage);
  const mobileHeaderCondensed = useUIStore((s) => s.mobileHeaderCondensed);

  const { tripInputs, dayCards, tiles } = useDocumentStore(
    useShallow((s) => ({
      tripInputs: s.document?.trip_inputs,
      dayCards: s.document?.day_cards,
      tiles: s.document?.tiles,
    }))
  );
  const hasDayCards = (dayCards?.length ?? 0) > 0;
  const tripContextId = useDocumentStore((s) => s.document?.trip_context_id);
  const { user, trips, userLoading, resumeTrip, resumingTripId } = useUserStore(
    useShallow((s) => ({
      user: s.user,
      trips: s.trips,
      userLoading: s.loading,
      resumeTrip: s.resumeTrip,
      resumingTripId: s.resumingTripId,
    }))
  );

  const otherTrips = useMemo(
    () => (tripContextId ? trips.filter((t) => t.trip_id !== tripContextId) : trips),
    [trips, tripContextId]
  );

  const closeMenu = useCallback(() => setMenuOpen(false), []);

  const {
    pdfState,
    shareState,
    handleNewTrip,
    handlePdfExport,
    handleShareTrip,
    handleLogin,
    handleLogout,
  } = useHeaderActions({
    dayCards,
    tripInputs,
    tiles,
    hasDayCards,
    onMenuClose: closeMenu,
  });

  useEffect(() => {
    if (activePage !== 1) return;
    const activeElement = document.activeElement;
    if (
      activeElement instanceof HTMLInputElement ||
      activeElement instanceof HTMLTextAreaElement
    ) {
      activeElement.blur();
    }
  }, [activePage]);

  const status = STATUS_CONFIG[planState];
  const destination = tripInputs?.destination?.trim() || '';
  const dateRangeText = (() => {
    if (!tripInputs?.start_date) return '';
    const start = new Date(tripInputs.start_date);
    const startFormatted = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    if (tripInputs.end_date) {
      const end = new Date(tripInputs.end_date);
      const endFormatted = end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      return `${startFormatted} - ${endFormatted}`;
    }
    return startFormatted;
  })();
  const condensedSummary = useMemo(() => {
    if (destination && dateRangeText) return `${destination} · ${dateRangeText}`;
    return destination || dateRangeText;
  }, [dateRangeText, destination]);
  const showCondensedBar = activePage === 1 && mobileHeaderCondensed && Boolean(condensedSummary);
  const handleScrollToTop = useCallback(() => {
    window.dispatchEvent(new Event(MOBILE_PLAN_SCROLL_TO_TOP_EVENT));
  }, []);

  // Don't render on desktop - split view shows both panels
  if (isDesktop) {
    return null;
  }

  return (
    <>
    <header
      className={cn(
        'fixed top-0 left-0 right-0 z-[1100]',
        'h-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]',
        'px-3 pt-[env(safe-area-inset-top)]',
        'flex items-center justify-between',
        'backdrop-blur',
        'border-b',
        'bg-background/80 border-border/50',
        'dark:bg-background/60 dark:border-border/30',
        'lg:hidden', // Only show on mobile
        className
      )}
    >
      {/* Left side: Nomadic branding (consistent across all modes) */}
      <div className="flex items-center gap-2">
        <Compass className="h-5 w-5 text-primary shrink-0" />
        <span className="font-semibold text-sm text-foreground">Nomadic</span>
      </div>

      {/* Right side: Menu only (status moved to floating pill below) */}
      <div className="flex items-center gap-2">
        {/* Menu button with Popover - deferred until mount to avoid Radix ID hydration mismatch */}
        {mounted ? (
          <Popover open={menuOpen} onOpenChange={setMenuOpen}>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="flex h-11 w-11 items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Menu"
              >
                <MoreVertical className="h-5 w-5" />
              </button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              className={cn('w-[200px] p-2', DS.materials.glass)}
            >
              <MobileHeaderMenu
                user={user}
                otherTrips={otherTrips}
                resumingTripId={resumingTripId}
                userLoading={userLoading}
                hasDayCards={hasDayCards}
                isResetting={isResetting}
                pdfState={pdfState}
                shareState={shareState}
                onNewTrip={handleNewTrip}
                onLogin={handleLogin}
                onLogout={handleLogout}
                onShareTrip={handleShareTrip}
                onPdfExport={handlePdfExport}
                onReset={onReset}
                onResumeTrip={resumeTrip}
                onClose={closeMenu}
              />
            </PopoverContent>
          </Popover>
        ) : (
          <button
            type="button"
            className="flex h-11 w-11 items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Menu"
          >
            <MoreVertical className="h-5 w-5" />
          </button>
        )}
      </div>
    </header>

    {showCondensedBar && (
      <div
        className={cn(
          'fixed left-0 right-0 z-[1098]',
          'top-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top))]',
          'h-14 px-4 flex items-center justify-between gap-3',
          'border-b backdrop-blur-xl',
          'bg-white/90 border-zinc-200',
          'dark:bg-zinc-950/80 dark:border-white/5',
          'lg:hidden'
        )}
      >
        <span className="min-w-0 truncate text-sm font-semibold text-zinc-900 dark:text-white">
          {condensedSummary}
        </span>
        <button
          type="button"
          onClick={handleScrollToTop}
          className={cn(
            'flex h-11 w-11 items-center justify-center rounded-full transition-colors',
            'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900',
            'dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-white'
          )}
          aria-label="Scroll plan to top"
        >
          <SlidersHorizontal className="h-5 w-5" />
        </button>
      </div>
    )}

    {/* Floating status pill -- centered below header, glass morphism */}
    {status.text && !showCondensedBar && (
      <div
        className={cn(
          'fixed z-[1099] left-1/2 -translate-x-1/2',
          'top-[calc(var(--mobile-header-height,48px)+env(safe-area-inset-top)+8px)]',
          'flex items-center gap-1.5',
          'px-3 py-1 rounded-full',
          'text-xs font-medium',
          'bg-background/80 backdrop-blur-md',
          'border border-border/40',
          'shadow-card',
          'lg:hidden',
          status.className
        )}
      >
        {status.icon}
        <span>{status.text}</span>
      </div>
    )}
    </>
  );
}

export const MobileModeHeader = memo(MobileModeHeaderInner);
