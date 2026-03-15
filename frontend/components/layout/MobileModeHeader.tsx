'use client';

import {
  Check,
  Loader2,
} from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { MobileHeaderMenu } from '@/components/layout/MobileHeaderMenu';
import { useHeaderActions } from '@/hooks/useHeaderActions';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import { useUIStore } from '@/state/uiStore';
import { useUserStore } from '@/state/userStore';
import type { PlanState } from '@/types/plan-envelope';

import {
  formatMobileHeaderDateRange,
  MobileModeCondensedBar,
  MobileModeHeaderShell,
  type MobileModeHeaderStatus,
  MobileModeStatusPill,
} from './MobileModeHeaderSections';

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

const STATUS_CONFIG: Record<PlanState, MobileModeHeaderStatus> = {
  INCOMPLETE: {
    text: '',
    className: 'text-zinc-500 dark:text-zinc-400',
  },
  RESOLVING: {
    text: 'Planning...',
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    className: 'text-emerald-600/80 dark:text-emerald-500/80',
  },
  STABLE: {
    text: '',
    icon: <Check className="h-3 w-3" />,
    className: 'text-emerald-600/80 dark:text-emerald-400/80',
  },
  LOCKED: {
    text: 'Locked',
    className: 'text-zinc-900 dark:text-white',
  },
};

const MOBILE_PLAN_SCROLL_TO_TOP_EVENT = 'nomadic:mobile-plan-scroll-top';

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

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
  const dateRangeText = formatMobileHeaderDateRange(
    tripInputs?.start_date,
    tripInputs?.end_date
  );
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
      <MobileModeHeaderShell
        mounted={mounted}
        menuOpen={menuOpen}
        onMenuOpenChange={setMenuOpen}
        className={className}
        menuContent={
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
        }
      />
      {showCondensedBar ? (
        <MobileModeCondensedBar
          summary={condensedSummary}
          onScrollToTop={handleScrollToTop}
        />
      ) : (
        <MobileModeStatusPill status={status} />
      )}
    </>
  );
}

export const MobileModeHeader = memo(MobileModeHeaderInner);
