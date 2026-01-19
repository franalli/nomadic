'use client';

import { Check, X } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { ReadinessItem } from '@/types/plan-envelope';
import { getReadinessLabel } from '@/types/plan-envelope';

interface ResolutionCompletenessProps {
  readiness: ReadinessItem[];
  className?: string;
}

/**
 * ResolutionCompleteness - Diagnostic panel showing constraint completeness.
 *
 * Renders a checklist of readiness items:
 * ✓ Origin
 * ✓ Destination
 * ✗ End date
 *
 * Rules:
 * - No buttons, no links, no suggestions
 * - Purely informational diagnostic
 * - Should only be visible when plan_state is INCOMPLETE or RESOLVING
 */
export const ResolutionCompleteness = memo(function ResolutionCompleteness({
  readiness,
  className,
}: ResolutionCompletenessProps) {
  if (!readiness || readiness.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        'rounded-md border border-border/20 bg-muted/20 px-3 py-2',
        className
      )}
    >
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 mb-1.5">
        Resolution status
      </div>
      <ul className="space-y-0.5">
        {readiness.map((item) => (
          <li
            key={item.key}
            className={cn(
              'flex items-center gap-2 text-xs',
              item.ok ? 'text-foreground/70' : 'text-muted-foreground/60'
            )}
          >
            {item.ok ? (
              <Check className="h-3 w-3 text-green-500 flex-shrink-0" />
            ) : (
              <X className="h-3 w-3 text-muted-foreground/40 flex-shrink-0" />
            )}
            <span className={cn(!item.ok && 'opacity-70')}>
              {getReadinessLabel(item.key)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
});
