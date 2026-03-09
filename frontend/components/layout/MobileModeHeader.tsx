'use client';

import {
  Check,
  Compass,
  Download,
  Loader2,
  LogIn,
  LogOut,
  MoreVertical,
  Plus,
  RotateCcw,
  Share2,
  SlidersHorizontal,
} from 'lucide-react';
import Link from 'next/link';
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useToast } from '@/components/ui/toast';
import { UserAvatar } from '@/components/ui/UserAvatar';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { apiFetch } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { extractTripPdfData } from '@/lib/pdfData';
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
const MOBILE_MENU_ITEM_CLASS =
  'flex w-full min-h-11 items-center gap-2 rounded-md px-2 text-left transition-colors';
const MOBILE_MENU_ACTION_CLASS = cn(
  MOBILE_MENU_ITEM_CLASS,
  'hover:bg-zinc-100 dark:hover:bg-white/10 disabled:pointer-events-none disabled:opacity-50'
);
const MOBILE_MENU_LINK_CLASS = `${MOBILE_MENU_ITEM_CLASS} hover:bg-muted`;

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * MobileModeHeader - Mobile-only header with consistent branding.
 *
 * DESIGN PRINCIPLE: Bottom tabs are the ONLY navigation method.
 * No "← Edit" back button - this creates a parallel workspace model
 * like Instagram, Airbnb, or Spotify where you tap tabs to switch views.
 *
 * Both Modes:
 * - Left: Nomadic logo + wordmark (brand anchor)
 * - Right: Menu (⋮) with Reset, Help & Legal
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
  const [pdfState, setPdfState] = useState<'idle' | 'loading'>('idle');
  const [shareState, setShareState] = useState<'idle' | 'loading' | 'copied'>('idle');
  const { toast } = useToast();
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
  const { user, trips, userLoading, login, logout, resumeTrip, resumingTripId } = useUserStore(
    useShallow((s) => ({
      user: s.user,
      trips: s.trips,
      userLoading: s.loading,
      login: s.login,
      logout: s.logout,
      resumeTrip: s.resumeTrip,
      resumingTripId: s.resumingTripId,
    }))
  );

  const otherTrips = useMemo(
    () => (tripContextId ? trips.filter((t) => t.trip_id !== tripContextId) : trips),
    [trips, tripContextId]
  );

  const handleNewTrip = useCallback(async () => {
    try {
      await apiFetch('/api/session/new', { method: 'POST' });
      window.location.reload();
    } catch {
      toast('Could not start new trip', { type: 'error' });
    }
  }, [toast]);

  const handlePdfExport = useCallback(async () => {
    if (pdfState === 'loading' || !dayCards?.length) return;
    setPdfState('loading');
    try {
      const [{ pdf }, { saveAs }, { TripPdfDocument }] = await Promise.all([
        import('@react-pdf/renderer'),
        import('file-saver'),
        import('@/components/plan/pdf/TripPdfDocument'),
      ]);
      const data = extractTripPdfData(tripInputs, dayCards, tiles ?? {});
      const blob = await pdf(<TripPdfDocument data={data} />).toBlob();
      const dest = (data.destination || 'Trip').replace(/\s+/g, '-');
      saveAs(blob, `${dest}.pdf`);
    } catch (err) {
      console.error('PDF export failed:', err);
      toast(err instanceof Error ? err.message : 'PDF export failed', { type: 'error' });
    } finally {
      setPdfState('idle');
      setMenuOpen(false);
    }
  }, [pdfState, tripInputs, dayCards, tiles, toast]);

  const handleShareTrip = useCallback(async () => {
    if (shareState === 'loading' || !hasDayCards) return;
    setShareState('loading');
    try {
      const res = await apiFetch('/api/share', { method: 'POST' });
      if (!res.ok) throw new Error('Failed to create share link');
      const data = await res.json();
      const shareUrl = typeof data?.url === 'string' ? data.url : null;
      const title = typeof data?.title === 'string' ? data.title : 'Shared Trip';
      if (!shareUrl) throw new Error('Share URL missing');

      if (navigator.share) {
        try {
          await navigator.share({ title, url: shareUrl });
          setShareState('idle');
          setMenuOpen(false);
          return;
        } catch {
          // User canceled native share; continue with clipboard fallback.
        }
      }

      await navigator.clipboard.writeText(shareUrl);
      setShareState('copied');
      window.setTimeout(() => setShareState('idle'), 2000);
      setMenuOpen(false);
    } catch (err) {
      console.error('Share failed:', err);
      toast(err instanceof Error ? err.message : 'Failed to share trip', { type: 'error' });
      setShareState('idle');
    }
  }, [hasDayCards, shareState, toast]);

  const handleLogin = useCallback(async () => {
    try {
      await login();
    } catch (err) {
      console.error('Login failed:', err);
    }
  }, [login]);

  const handleLogout = useCallback(async () => {
    await logout();
    setMenuOpen(false);
  }, [logout]);

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
  const dateRangeText = useMemo(() => {
    if (!tripInputs?.start_date) return '';
    const start = new Date(tripInputs.start_date);
    const startFormatted = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    if (tripInputs.end_date) {
      const end = new Date(tripInputs.end_date);
      const endFormatted = end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      return `${startFormatted} - ${endFormatted}`;
    }
    return startFormatted;
  }, [tripInputs?.end_date, tripInputs?.start_date]);
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
              <nav className="flex flex-col">
                {user ? (
                  <>
                    <div className="px-2 py-2 border-b border-border mb-1">
                      <div className="flex items-center gap-2">
                        <UserAvatar
                          src={user.avatar_url}
                          alt={user.name || user.email}
                          imageClassName="h-6 w-6 rounded-full object-cover"
                          iconClassName="h-5 w-5"
                        />
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-foreground truncate">{user.name || user.email}</p>
                          <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                        </div>
                      </div>
                    </div>
                    {otherTrips.length > 0 && (
                      <div className="px-2 pb-2">
                        <p className={`${DS.textSize.micro} font-bold uppercase tracking-widest text-muted-foreground mb-1`}>Recent Trips</p>
                        <div className="space-y-1">
                          {otherTrips.slice(0, 3).map((trip) => {
                            const isPast = trip.end_date && new Date(trip.end_date) < new Date();
                            return (
                              <button
                                key={`${trip.trip_id}-${trip.updated_at}`}
                                type="button"
                                disabled={resumingTripId !== null}
                                onClick={async () => {
                                  const ok = await resumeTrip(trip.trip_id);
                                  if (!ok) toast('Could not open saved trip', { type: 'error' });
                                }}
                                className={cn(
                                  'w-full min-h-11 rounded-lg px-2 py-2 text-left transition-colors outline-none focus-visible:ring-1 focus-visible:ring-white/20 hover:bg-white/[0.06] disabled:pointer-events-none disabled:opacity-50',
                                  isPast && 'opacity-60'
                                )}
                              >
                                <p className="text-xs text-foreground truncate">
                                  {trip.destination || 'Untitled Trip'}
                                </p>
                                <p className={`${DS.textSize.micro} text-muted-foreground`}>
                                  {resumingTripId === trip.trip_id
                                    ? 'Opening...'
                                    : trip.day_count > 0
                                    ? `${trip.day_count} days${isPast ? ' (Past)' : ''}`
                                    : 'No itinerary yet'}
                                </p>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={handleNewTrip}
                      className={cn(
                        MOBILE_MENU_ACTION_CLASS,
                        'rounded-lg outline-none focus-visible:ring-1 focus-visible:ring-white/20 hover:bg-white/[0.06] text-foreground'
                      )}
                    >
                      <Plus className="h-3.5 w-3.5" />
                      <span className={DS.textSize.micro}>New Trip</span>
                    </button>
                    <button
                      type="button"
                      onClick={handleLogout}
                      className={cn(
                        MOBILE_MENU_ACTION_CLASS,
                        'rounded-lg outline-none focus-visible:ring-1 focus-visible:ring-white/20 hover:bg-white/[0.06] text-foreground'
                      )}
                    >
                      <LogOut className="h-3.5 w-3.5" />
                      <span className={DS.textSize.micro}>Sign out</span>
                    </button>
                    <div className="h-px bg-border my-1" />
                  </>
                ) : (
                  <>
                    {onReset && (
                      <>
                        <button
                          type="button"
                          disabled={isResetting}
                          onClick={() => {
                            if (isResetting) return;
                            setMenuOpen(false);
                            onReset();
                          }}
                          className={cn(
                            MOBILE_MENU_ACTION_CLASS,
                            'font-bold uppercase tracking-widest text-zinc-900 dark:text-white',
                            DS.textSize.micro
                          )}
                        >
                          {isResetting ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <RotateCcw className="h-3.5 w-3.5" />
                          )}
                          <span>{isResetting ? 'Resetting...' : 'Reset Trip'}</span>
                        </button>
                        <div className="h-px bg-border my-1" />
                      </>
                    )}
                    <button
                      type="button"
                      onClick={handleLogin}
                      disabled={userLoading}
                      className={cn(
                        MOBILE_MENU_ACTION_CLASS,
                        'text-zinc-900 dark:text-white'
                      )}
                    >
                      {userLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LogIn className="h-3.5 w-3.5" />}
                      <span className={DS.textSize.micro}>Sign in</span>
                    </button>
                    <div className="h-px bg-border my-1" />
                  </>
                )}

                {/* Reset - moved inside menu to prevent accidental taps */}
                {user && onReset && (
                  <>
                    <button
                      type="button"
                      disabled={isResetting}
                      onClick={() => {
                        if (isResetting) return;
                        setMenuOpen(false);
                        onReset();
                      }}
                      className={cn(
                        MOBILE_MENU_ACTION_CLASS,
                        'font-bold uppercase tracking-widest text-zinc-900 dark:text-white',
                        DS.textSize.micro
                      )}
                    >
                      {isResetting ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5" />
                      )}
                      <span>{isResetting ? 'Resetting...' : 'Reset Trip'}</span>
                    </button>
                    <div className="h-px bg-border my-1" />
                  </>
                )}

                {hasDayCards && (
                  <>
                    <button
                      type="button"
                      disabled={shareState === 'loading'}
                      onClick={handleShareTrip}
                      className={cn(
                        MOBILE_MENU_ACTION_CLASS,
                        'font-bold uppercase tracking-widest text-zinc-900 dark:text-white',
                        DS.textSize.micro
                      )}
                    >
                      {shareState === 'loading' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : shareState === 'copied' ? (
                        <Check className="h-3.5 w-3.5 text-emerald-500" />
                      ) : (
                        <Share2 className="h-3.5 w-3.5" />
                      )}
                      <span>
                        {shareState === 'copied' ? 'Copied Link' : 'Share Trip'}
                      </span>
                    </button>
                    <div className="h-px bg-border my-1" />

                    <button
                      type="button"
                      disabled={pdfState === 'loading'}
                      onClick={handlePdfExport}
                      className={cn(
                        MOBILE_MENU_ACTION_CLASS,
                        'font-bold uppercase tracking-widest text-zinc-900 dark:text-white',
                        DS.textSize.micro
                      )}
                    >
                      {pdfState === 'loading' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Download className="h-3.5 w-3.5" />
                      )}
                      <span>{pdfState === 'loading' ? 'Exporting...' : 'Download PDF'}</span>
                    </button>
                    <div className="h-px bg-border my-1" />
                  </>
                )}

                <span className="px-2 py-1.5 text-xs font-medium text-muted-foreground">Help & Legal</span>
                <Link
                  href="/privacy"
                  className={MOBILE_MENU_LINK_CLASS}
                  onClick={() => setMenuOpen(false)}
                >
                  Privacy Policy
                </Link>
                <Link
                  href="/terms"
                  className={MOBILE_MENU_LINK_CLASS}
                  onClick={() => setMenuOpen(false)}
                >
                  Terms of Service
                </Link>
                <Link
                  href="/cookies"
                  className={MOBILE_MENU_LINK_CLASS}
                  onClick={() => setMenuOpen(false)}
                >
                  Cookie Policy
                </Link>
                <Link
                  href="/contact"
                  className={MOBILE_MENU_LINK_CLASS}
                  onClick={() => setMenuOpen(false)}
                >
                  Contact Us
                </Link>
              </nav>
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

    {/* Floating status pill — centered below header, glass morphism */}
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
