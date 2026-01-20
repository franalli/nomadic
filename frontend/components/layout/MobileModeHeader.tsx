'use client';

import { ArrowLeft, Check, Loader2 } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import { useMobileMode } from '@/contexts/MobileModeContext';
import type { PlanState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MobileModeHeaderProps {
  /** Current plan state for status display in Plan Mode */
  planState?: PlanState;
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
    text: 'Up to date',
    icon: <Check className="h-3 w-3" />,
    className: 'text-green-600/80',
  },
  LOCKED: {
    text: 'Locked',
    className: 'text-foreground',
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * MobileModeHeader - Mobile-only header with mode-aware content.
 *
 * Planner Mode:
 * - Left: "Travel planner" (minimal branding)
 * - Right: (empty or subtle status placeholder)
 *
 * Plan Mode:
 * - Left: "← Edit" back button
 * - Right: Status text ("Planning…" or "Up to date")
 */
function MobileModeHeaderInner({ planState = 'INCOMPLETE', className }: MobileModeHeaderProps) {
  const { mode, isDesktop, switchToPlanner } = useMobileMode();

  // Don't render on desktop - split view shows both panels
  if (isDesktop) {
    return null;
  }

  const isPlanMode = mode === 'plan';
  const status = STATUS_CONFIG[planState];

  return (
    <header
      className={cn(
        'sticky top-0 z-40',
        'h-12 px-4',
        'flex items-center justify-between',
        'bg-background/95 backdrop-blur',
        'border-b border-border/50',
        'lg:hidden', // Only show on mobile
        className
      )}
    >
      {/* Left side */}
      {isPlanMode ? (
        // Plan Mode: Edit back button
        <button
          type="button"
          onClick={switchToPlanner}
          className={cn(
            'flex items-center gap-1.5',
            'text-sm font-medium text-foreground',
            'hover:text-primary transition-colors',
            '-ml-1 px-1 py-1' // Expand tap target
          )}
          aria-label="Edit trip constraints"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Edit</span>
        </button>
      ) : (
        // Planner Mode: Minimal branding
        <span className="text-sm font-medium text-muted-foreground">
          Travel planner
        </span>
      )}

      {/* Right side */}
      {isPlanMode && status.text && (
        <div
          className={cn(
            'flex items-center gap-1.5 text-xs font-medium',
            status.className
          )}
        >
          {status.icon}
          <span>{status.text}</span>
        </div>
      )}
    </header>
  );
}

export const MobileModeHeader = memo(MobileModeHeaderInner);
