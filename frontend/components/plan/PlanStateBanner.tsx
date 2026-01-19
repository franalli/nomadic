'use client';

import { Check, Loader2, Lock } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { PlanState } from '@/types/plan-envelope';

interface PlanStateBannerProps {
  planState: PlanState;
  className?: string;
}

/**
 * PlanStateBanner - Single source of truth for plan state display.
 *
 * Renders exactly one line based on plan_state with strict rules:
 * - No secondary text inside banner
 * - No buttons inside banner
 * - No percentages, no ETA
 *
 * States:
 * - INCOMPLETE: "Plan incomplete · Add missing constraints" (muted)
 * - RESOLVING: "Updating plan" (emphasized, subtle pulse)
 * - STABLE: "Plan up to date" (calm)
 * - LOCKED: "Plan locked · Ready to book" (solid)
 */
export const PlanStateBanner = memo(function PlanStateBanner({
  planState,
  className,
}: PlanStateBannerProps) {
  // Banner configuration based on plan state
  const config: Record<
    PlanState,
    {
      text: string;
      dotColor: string;
      textColor: string;
      bgColor: string;
      animate?: boolean;
      icon?: React.ReactNode;
    }
  > = {
    INCOMPLETE: {
      text: 'Plan incomplete · Add missing constraints',
      dotColor: 'bg-muted-foreground/50',
      textColor: 'text-muted-foreground',
      bgColor: 'bg-muted/30',
    },
    RESOLVING: {
      text: 'Updating plan',
      dotColor: 'bg-primary',
      textColor: 'text-primary/80',
      bgColor: 'bg-primary/5',
      animate: true,
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
    },
    STABLE: {
      text: 'Plan up to date',
      dotColor: 'bg-green-500',
      textColor: 'text-green-600/80',
      bgColor: 'bg-green-500/5',
      icon: <Check className="h-3 w-3" />,
    },
    LOCKED: {
      text: 'Plan locked · Ready to book',
      dotColor: 'bg-foreground',
      textColor: 'text-foreground',
      bgColor: 'bg-foreground/5',
      icon: <Lock className="h-3 w-3" />,
    },
  };

  const { text, dotColor, textColor, bgColor, animate, icon } = config[planState];

  return (
    <div
      className={cn(
        'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium',
        'border border-border/20',
        bgColor,
        textColor,
        className
      )}
    >
      {/* Status indicator dot */}
      <span
        className={cn('h-1.5 w-1.5 rounded-full flex-shrink-0', dotColor, animate && 'animate-pulse')}
      />

      {/* Icon (if present) */}
      {icon}

      {/* Single-line text */}
      <span className="truncate">{text}</span>
    </div>
  );
});
