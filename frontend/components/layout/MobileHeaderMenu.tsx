'use client';

import {
  Check,
  Download,
  Loader2,
  LogIn,
  LogOut,
  Plus,
  RotateCcw,
  Share2,
} from 'lucide-react';
import Link from 'next/link';
import { memo } from 'react';

import { useToast } from '@/components/ui/toast';
import { UserAvatar } from '@/components/ui/UserAvatar';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { AuthUser, UserTripSummary } from '@/state/userStore';

// ─────────────────────────────────────────────────────────────────────────────
// Constants (duplicated from MobileModeHeader — shared menu styling)
// ─────────────────────────────────────────────────────────────────────────────

const MOBILE_MENU_ITEM_CLASS =
  'flex w-full min-h-11 items-center gap-2 rounded-md px-2 text-left transition-colors';
const MOBILE_MENU_ACTION_CLASS = cn(
  MOBILE_MENU_ITEM_CLASS,
  'hover:bg-zinc-100 dark:hover:bg-white/10 disabled:pointer-events-none disabled:opacity-50'
);
const MOBILE_MENU_LINK_CLASS = `${MOBILE_MENU_ITEM_CLASS} hover:bg-muted`;

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MobileHeaderMenuProps {
  // User data
  user: AuthUser | null;
  otherTrips: UserTripSummary[];
  resumingTripId: number | null;
  userLoading: boolean;
  // Trip state
  hasDayCards: boolean;
  isResetting: boolean;
  // Actions from useHeaderActions
  pdfState: 'idle' | 'loading';
  shareState: 'idle' | 'loading' | 'copied';
  onNewTrip: () => void;
  onLogin: () => void;
  onLogout: () => void;
  onShareTrip: () => void;
  onPdfExport: () => void;
  onReset: (() => void) | undefined;
  onResumeTrip: (tripId: number) => Promise<boolean>;
  onClose: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function MobileHeaderMenuInner({
  user,
  otherTrips,
  resumingTripId,
  userLoading,
  hasDayCards,
  isResetting,
  pdfState,
  shareState,
  onNewTrip,
  onLogin,
  onLogout,
  onShareTrip,
  onPdfExport,
  onReset,
  onResumeTrip,
  onClose,
}: MobileHeaderMenuProps) {
  const { toast } = useToast();

  return (
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
                        const ok = await onResumeTrip(trip.trip_id);
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
            onClick={onNewTrip}
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
            onClick={onLogout}
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
                  onClose();
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
            onClick={onLogin}
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
              onClose();
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
            onClick={onShareTrip}
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
            onClick={onPdfExport}
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
        onClick={onClose}
      >
        Privacy Policy
      </Link>
      <Link
        href="/terms"
        className={MOBILE_MENU_LINK_CLASS}
        onClick={onClose}
      >
        Terms of Service
      </Link>
      <Link
        href="/cookies"
        className={MOBILE_MENU_LINK_CLASS}
        onClick={onClose}
      >
        Cookie Policy
      </Link>
      <Link
        href="/contact"
        className={MOBILE_MENU_LINK_CLASS}
        onClick={onClose}
      >
        Contact Us
      </Link>
    </nav>
  );
}

export const MobileHeaderMenu = memo(MobileHeaderMenuInner);
