import Link from 'next/link';
import type { ReactNode } from 'react';

import { UserAvatar } from '@/components/ui/UserAvatar';
import { DS } from '@/lib/design-system';
import { cn, formatDateForDisplay } from '@/lib/utils';
import type { AuthUser, UserTripSummary } from '@/state/userStore';

const HEADER_MENU_ITEM_CLASS = 'flex w-full min-h-11 items-center gap-2 rounded-md px-2 text-left transition-colors';
const HEADER_MENU_FOCUS_CLASS = 'rounded-lg outline-none focus-visible:ring-1 focus-visible:ring-white/20';
const RECENT_TRIP_BASE_CLASS = 'w-full text-left transition-colors disabled:pointer-events-none disabled:opacity-50';

const HEADER_MENU_ACTION_CLASS = cn(
  HEADER_MENU_ITEM_CLASS,
  'hover:bg-zinc-100 dark:hover:bg-white/10 disabled:pointer-events-none disabled:opacity-50'
);
const HEADER_MENU_LINK_CLASS = `${HEADER_MENU_ITEM_CLASS} hover:bg-zinc-100 dark:hover:bg-white/10`;

type RecentTripsVariant = 'mobile' | 'desktop';
const HELP_LINKS = [['privacy', 'Privacy Policy'], ['terms', 'Terms of Service'], ['cookies', 'Cookie Policy'], ['contact', 'Contact Us']] as const;

const RECENT_TRIPS_VARIANTS = {
  mobile: {
    headingClassName: cn(
      DS.textSize.micro,
      'mb-1 font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400'
    ),
    listClassName: 'space-y-1',
    itemClassName: cn(
      RECENT_TRIP_BASE_CLASS,
      HEADER_MENU_FOCUS_CLASS,
      'min-h-11 px-2 py-2 hover:bg-white/[0.06]'
    ),
    titleClassName: 'text-xs text-zinc-900 dark:text-white truncate',
    metaClassName: `${DS.textSize.micro} text-zinc-500 dark:text-zinc-400`,
  },
  desktop: {
    headingClassName: 'mb-2 text-xs font-medium uppercase tracking-widest text-zinc-500 dark:text-zinc-400',
    listClassName: 'space-y-1.5',
    itemClassName: cn(
      RECENT_TRIP_BASE_CLASS,
      HEADER_MENU_FOCUS_CLASS,
      'px-2 py-1.5 hover:bg-white/[0.06]'
    ),
    titleClassName: 'text-xs font-medium text-zinc-900 dark:text-white truncate',
    metaClassName: 'text-xs text-zinc-500 dark:text-zinc-400',
  },
} as const;

export function HeaderMenuUserProfile({
  user,
  className,
  showAvatar = false,
}: { user: AuthUser; className?: string; showAvatar?: boolean }) {
  return (
    <div className={cn('mb-1 border-b border-zinc-200 dark:border-white/10 px-2 py-2', className)}>
      <div className="flex items-center gap-2">
        {showAvatar ? (
          <UserAvatar
            src={user.avatar_url}
            alt={user.name || user.email}
            imageClassName="h-6 w-6 rounded-full object-cover"
            iconClassName="h-5 w-5"
          />
        ) : null}
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-zinc-900 dark:text-white">{user.name || user.email}</p>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">{user.email}</p>
        </div>
      </div>
    </div>
  );
}

export function HeaderMenuRecentTrips({
  trips,
  resumingTripId,
  onResume,
  onResumeError,
  variant,
  getTripMeta,
  heading = 'Recent Trips',
  emptyCopy,
  maxItems = 5,
  className,
}: {
  trips: UserTripSummary[];
  resumingTripId: number | null;
  onResume: (tripId: number) => Promise<boolean>;
  onResumeError: () => void;
  variant: RecentTripsVariant;
  getTripMeta: (trip: UserTripSummary, isPast: boolean) => string;
  heading?: string;
  emptyCopy?: string;
  maxItems?: number;
  className?: string;
}) {
  const styles = RECENT_TRIPS_VARIANTS[variant];
  const visibleTrips = trips.slice(0, maxItems);

  return (
    <div className={cn('px-2 pb-2', className)}>
      <p className={styles.headingClassName}>{heading}</p>
      {visibleTrips.length === 0 ? (
        emptyCopy ? <p className={styles.metaClassName}>{emptyCopy}</p> : null
      ) : (
        <div className={styles.listClassName}>
          {visibleTrips.map((trip) => {
            const isPast = trip.end_date ? new Date(trip.end_date) < new Date() : false;
            const isOpening = resumingTripId === trip.trip_id;

            return (
              <button
                key={`${trip.trip_id}-${trip.updated_at}`}
                type="button"
                disabled={resumingTripId !== null}
                onClick={async () => {
                  const ok = await onResume(trip.trip_id);
                  if (!ok) onResumeError();
                }}
                className={cn(styles.itemClassName, isPast && 'opacity-60')}
              >
                <p className={styles.titleClassName}>{trip.destination || 'Untitled Trip'}</p>
                <p className={styles.metaClassName}>
                  {isOpening ? 'Opening...' : getTripMeta(trip, isPast)}
                </p>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function HeaderMenuActionButton({
  icon,
  label,
  onClick,
  disabled = false,
  className,
  labelClassName,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
  className?: string;
  labelClassName?: string;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        HEADER_MENU_ACTION_CLASS,
        HEADER_MENU_FOCUS_CLASS,
        'hover:bg-white/[0.06]',
        className
      )}
    >
      {icon}
      <span className={labelClassName}>{label}</span>
    </button>
  );
}

export function HeaderMenuDivider() {
  return <div className="my-1 h-px bg-zinc-200 dark:bg-white/10" />;
}

export function HeaderMenuLegalLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <span className="px-2 py-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">Help & Legal</span>
      {HELP_LINKS.map(([href, label]) => (
        <Link key={href} href={`/${href}`} className={HEADER_MENU_LINK_CLASS} onClick={onNavigate}>
          {label}
        </Link>
      ))}
    </>
  );
}

export function getMobileTripMeta(trip: UserTripSummary, isPast: boolean): string {
  if (trip.day_count > 0) {
    return `${trip.day_count} days${isPast ? ' (Past)' : ''}`;
  }
  return 'No itinerary yet';
}

export function getDesktopTripMeta(trip: UserTripSummary, isPast: boolean): string {
  if (trip.start_date && trip.end_date) {
    return `${formatDateForDisplay(trip.start_date)} - ${formatDateForDisplay(trip.end_date)}${isPast ? ' (Past)' : ''}`;
  }
  return 'Dates not set';
}
