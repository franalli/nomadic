'use client';

import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

interface CountBadgeProps {
  count: number;
}

function CountBadge({ count }: CountBadgeProps) {
  return (
    <span
      className={cn(
        'ml-0.5 inline-flex min-w-[18px] items-center justify-center rounded-full px-1',
        'h-[18px] bg-white text-zinc-900',
        DS.textSize.micro,
        'font-bold'
      )}
    >
      {count}
    </span>
  );
}

export interface TripSummarySegmentProps {
  icon: LucideIcon;
  label: string;
  badge?: number;
  isSet?: boolean;
  muted?: boolean;
  active?: boolean;
  disabled?: boolean;
  compact?: boolean;
  onClick?: () => void;
  id?: string;
  ariaControls?: string;
  ariaExpanded?: boolean;
  trailing?: ReactNode;
}

export function TripSummarySegment({
  icon: Icon,
  label,
  badge,
  isSet = false,
  muted = false,
  active = false,
  disabled = false,
  compact = false,
  onClick,
  id,
  ariaControls,
  ariaExpanded,
  trailing,
}: TripSummarySegmentProps) {
  const interactive = Boolean(onClick) && !disabled;

  return (
    <button
      id={id}
      type="button"
      onClick={onClick}
      disabled={!interactive}
      aria-controls={ariaControls}
      aria-expanded={ariaExpanded}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full whitespace-nowrap transition-all duration-150',
        compact ? 'h-8 px-2 text-xs' : `h-10 px-3 ${DS.textSize.badgeLabel}`,
        'hover:bg-white/[0.08]',
        interactive ? 'cursor-pointer' : 'cursor-default opacity-70',
        muted
          ? cn(active ? 'text-zinc-200' : 'text-zinc-400', 'font-medium hover:text-zinc-200')
          : isSet
            ? 'font-semibold text-zinc-100'
            : 'text-zinc-500'
      )}
    >
      <Icon
        className={cn(
          'h-4 w-4 shrink-0',
          muted ? cn(active ? 'text-zinc-300' : 'text-zinc-500') : isSet ? 'text-emerald-400/80' : 'text-zinc-600'
        )}
      />
      <span>{label}</span>
      {trailing}
      {badge && badge > 0 ? <CountBadge count={badge} /> : null}
    </button>
  );
}

export function TripSummarySegmentDot() {
  return (
    <div className="flex items-center px-1.5">
      <div className={cn('h-1 w-1 rounded-full bg-emerald-500/50', DS.glowClass.dotGlow)} />
    </div>
  );
}

export function TripSummaryGroupDivider() {
  return (
    <div className="flex items-center px-2">
      <div className="h-5 w-px bg-white/[0.15]" />
    </div>
  );
}
