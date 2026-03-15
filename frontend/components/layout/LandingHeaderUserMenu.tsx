'use client';

import { LogOut, Plus } from 'lucide-react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { ToastType } from '@/components/ui/toast';
import { UserAvatar } from '@/components/ui/UserAvatar';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { AuthUser, UserTripSummary } from '@/state/userStore';

import {
  getDesktopTripMeta,
  HeaderMenuActionButton,
  HeaderMenuRecentTrips,
  HeaderMenuUserProfile,
} from './headerMenuParts';

interface LandingHeaderUserMenuProps {
  user: AuthUser;
  otherTrips: UserTripSummary[];
  resumingTripId: number | null;
  handleNewTrip: () => Promise<void>;
  handleLogout: () => Promise<void>;
  resumeTrip: (tripId: number) => Promise<boolean>;
  addToast: (message: string, type?: ToastType) => void;
}

export function LandingHeaderUserMenu({
  user,
  otherTrips,
  resumingTripId,
  handleNewTrip,
  handleLogout,
  resumeTrip,
  addToast,
}: LandingHeaderUserMenuProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border border-zinc-300 bg-zinc-100 dark:border-white/15 dark:bg-white/10"
          aria-label="User menu"
        >
          <UserAvatar
            src={user.avatar_url}
            alt={user.name || user.email}
            imageClassName="h-full w-full object-cover"
            iconClassName="h-4 w-4 text-zinc-600 dark:text-zinc-300"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className={cn('w-[280px] p-2', DS.materials.glass)}>
        <HeaderMenuUserProfile user={user} className="mb-2 px-2 py-1.5" />
        <HeaderMenuRecentTrips
          trips={otherTrips}
          resumingTripId={resumingTripId}
          onResume={resumeTrip}
          onResumeError={() => addToast('Could not open saved trip', 'error')}
          variant="desktop"
          getTripMeta={getDesktopTripMeta}
          emptyCopy="No saved trips yet."
        />
        <HeaderMenuActionButton
          icon={<Plus className="h-4 w-4" />}
          label="New Trip"
          onClick={handleNewTrip}
          className="text-zinc-900 dark:text-white"
          labelClassName="text-sm"
        />
        <HeaderMenuActionButton
          icon={<LogOut className="h-4 w-4" />}
          label="Sign out"
          onClick={handleLogout}
          className="text-zinc-900 dark:text-white"
          labelClassName="text-sm"
        />
      </PopoverContent>
    </Popover>
  );
}
