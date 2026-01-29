/**
 * MobileChatCompactHeader
 *
 * Compact sticky header shown in Chat tab after plan generation.
 * Replaces the hero banner in post-plan mobile view.
 *
 * Shows:
 * - Status indicator with pulse animation ("AI Architect Active")
 * - Scrollable trip summary pills (destination, dates, travelers)
 *
 * Uses glassmorphism for native app feel - separates from scrolling chat.
 */

'use client';

import { Check, Loader2 } from 'lucide-react';
import { memo } from 'react';

import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { PlanState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

// ─────────────────────────────────────────────────────────────────────────────
// Status Configuration (mirrors MobileModeHeader)
// ─────────────────────────────────────────────────────────────────────────────

function getStatusConfig(planState: PlanState): {
  text: string;
  dotColor: string;
  icon?: React.ReactNode;
} {
  switch (planState) {
    case 'RESOLVING':
      return {
        text: 'Updating plan...',
        dotColor: 'bg-emerald-500',
        icon: <Loader2 className="h-2.5 w-2.5 animate-spin" />,
      };
    case 'STABLE':
      return {
        text: 'Plan ready',
        dotColor: 'bg-emerald-500',
        icon: <Check className="h-2.5 w-2.5" />,
      };
    case 'LOCKED':
      return {
        text: 'Plan locked',
        dotColor: 'bg-zinc-400',
      };
    case 'INCOMPLETE':
    default:
      return {
        text: 'AI Architect Active',
        dotColor: 'bg-emerald-500 animate-pulse',
      };
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

interface MobileChatCompactHeaderProps {
  tripInputs?: DocumentTripInputs;
  planState?: PlanState;
  onOpenSheet?: (sheet: SheetType) => void;
  className?: string;
}

function MobileChatCompactHeaderInner({
  tripInputs,
  planState = 'STABLE',
  onOpenSheet,
  className,
}: MobileChatCompactHeaderProps) {
  const status = getStatusConfig(planState);

  return (
    <div
      className={cn(
        // Glassmorphism: semi-transparent with blur
        'sticky top-0 z-40 w-full',
        'bg-white/80 dark:bg-zinc-900/80 backdrop-blur-md',
        'border-b border-zinc-200 dark:border-white/5',
        'px-4 py-3',
        '-mx-4 -mt-4 mb-2', // Bleed to edges, negative margin to counteract padding
        'w-[calc(100%+2rem)]', // Full width including padding compensation
        'transition-all duration-300',
        className
      )}
    >
      {/* 1. Status & Title Row */}
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          {/* Pulse dot */}
          <div className={cn('w-2 h-2 rounded-full', status.dotColor)} />
          {/* Status text */}
          <span className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest">
            {status.text}
          </span>
          {/* Optional spinning icon */}
          {status.icon && (
            <span className="text-zinc-400 dark:text-zinc-500">{status.icon}</span>
          )}
        </div>
      </div>

      {/* 2. Scrollable Pill Row (The Context) */}
      {tripInputs && onOpenSheet && (
        <div className="overflow-x-auto no-scrollbar -mx-1 px-1">
          <TripSummaryPills
            tripInputs={tripInputs}
            onOpenSheet={onOpenSheet}
            disabled={planState === 'RESOLVING'}
          />
        </div>
      )}
    </div>
  );
}

export const MobileChatCompactHeader = memo(MobileChatCompactHeaderInner);

export default MobileChatCompactHeader;
