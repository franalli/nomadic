'use client';

import { Check, Download, Loader2, LogIn, LogOut, Plus, RotateCcw, Share2 } from 'lucide-react';
import { memo } from 'react';

import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { AuthUser, UserTripSummary } from '@/state/userStore';

import {
  getMobileTripMeta,
  HeaderMenuActionButton,
  HeaderMenuDivider,
  HeaderMenuLegalLinks,
  HeaderMenuRecentTrips,
  HeaderMenuUserProfile,
} from './headerMenuParts';

interface MobileHeaderMenuProps {
  user: AuthUser | null;
  otherTrips: UserTripSummary[];
  resumingTripId: number | null;
  userLoading: boolean;
  hasDayCards: boolean;
  isResetting: boolean;
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
  const resetLabel = isResetting ? 'Resetting...' : 'Reset Trip';

  return (
    <nav className="flex flex-col">
      {user ? (
        <>
          <HeaderMenuUserProfile user={user} showAvatar />
          {otherTrips.length > 0 && (
            <HeaderMenuRecentTrips
              trips={otherTrips}
              resumingTripId={resumingTripId}
              onResume={onResumeTrip}
              onResumeError={() => toast('Could not open saved trip', { type: 'error' })}
              variant="mobile"
              getTripMeta={getMobileTripMeta}
              maxItems={3}
            />
          )}
          <HeaderMenuActionButton icon={<Plus className="h-3.5 w-3.5" />} label="New Trip" onClick={onNewTrip} className="text-zinc-900 dark:text-white" labelClassName={DS.textSize.micro} />
          <HeaderMenuActionButton icon={<LogOut className="h-3.5 w-3.5" />} label="Sign out" onClick={onLogout} className="text-zinc-900 dark:text-white" labelClassName={DS.textSize.micro} />
          <HeaderMenuDivider />
        </>
      ) : (
        <>
          {onReset && (
            <>
              <HeaderMenuActionButton
                icon={
                  isResetting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RotateCcw className="h-3.5 w-3.5" />
                  )
                }
                label={resetLabel}
                onClick={() => {
                  if (isResetting) return;
                  onClose();
                  onReset();
                }}
                disabled={isResetting}
                className={cn('font-bold uppercase tracking-widest text-zinc-900 dark:text-white', DS.textSize.micro)}
              />
              <HeaderMenuDivider />
            </>
          )}
          <HeaderMenuActionButton
            icon={
              userLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <LogIn className="h-3.5 w-3.5" />
              )
            }
            label="Sign in"
            onClick={onLogin}
            disabled={userLoading}
            className="text-zinc-900 dark:text-white" labelClassName={DS.textSize.micro}
          />
          <HeaderMenuDivider />
        </>
      )}

      {user && onReset && (
        <>
          <HeaderMenuActionButton
            icon={
              isResetting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )
            }
            label={resetLabel}
            onClick={() => {
              if (isResetting) return;
              onClose();
              onReset();
            }}
            disabled={isResetting}
            className={cn('font-bold uppercase tracking-widest text-zinc-900 dark:text-white', DS.textSize.micro)}
          />
          <HeaderMenuDivider />
        </>
      )}

      {hasDayCards && (
        <>
          <HeaderMenuActionButton
            icon={
              shareState === 'loading' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : shareState === 'copied' ? (
                <Check className="h-3.5 w-3.5 text-emerald-500" />
              ) : (
                <Share2 className="h-3.5 w-3.5" />
              )
            }
            label={shareState === 'copied' ? 'Copied Link' : 'Share Trip'}
            onClick={onShareTrip}
            disabled={shareState === 'loading'}
            className={cn('font-bold uppercase tracking-widest text-zinc-900 dark:text-white', DS.textSize.micro)}
          />
          <HeaderMenuDivider />

          <HeaderMenuActionButton
            icon={
              pdfState === 'loading' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )
            }
            label={pdfState === 'loading' ? 'Exporting...' : 'Download PDF'}
            onClick={onPdfExport}
            disabled={pdfState === 'loading'}
            className={cn('font-bold uppercase tracking-widest text-zinc-900 dark:text-white', DS.textSize.micro)}
          />
          <HeaderMenuDivider />
        </>
      )}

      <HeaderMenuLegalLinks onNavigate={onClose} />
    </nav>
  );
}

export const MobileHeaderMenu = memo(MobileHeaderMenuInner);
