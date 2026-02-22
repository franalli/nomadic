'use client';

import { Brain, ChevronDown } from 'lucide-react';
import type { ReactNode } from 'react';

import { NICHE_SPECIALIST_IDS } from '@/lib/specialists';
import { cn } from '@/lib/utils';
import type { PlanViewModel } from '@/types/plan-envelope';

interface StrategyConstraintBarProps {
  fullModeSections: PlanViewModel['strategy_sections'];
  hasItineraryContent: boolean;
  showConstraints: boolean;
  onToggleConstraints: () => void;
}

/** Action pill bar — Specialists (engine constraints) toggle only. */
export function StrategyConstraintBar({
  fullModeSections,
  hasItineraryContent,
  showConstraints,
  onToggleConstraints,
}: StrategyConstraintBarProps): ReactNode {
  const engineConstraints = (fullModeSections ?? [])
    .filter((s) => NICHE_SPECIALIST_IDS.includes(s.specialist_type || ''))
    .flatMap((s) => s.constraints_applied || [])
    .filter((c) => {
      const sev = (c as Record<string, string>).severity;
      return !sev || sev === 'blocking' || sev === 'strong';
    });

  const hasActionPills = hasItineraryContent && engineConstraints.length > 0;

  if (!hasActionPills) return null;

  return (
    <div className="flex items-center justify-center gap-1.5 flex-wrap px-4 py-1.5">
      <button
        type="button"
        onClick={onToggleConstraints}
        className={cn(
          'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs whitespace-nowrap transition-all duration-150',
          'border-zinc-300 dark:border-white/15 bg-zinc-100 dark:bg-white/[0.06]',
          'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-white/10',
        )}
      >
        <Brain className="w-3 h-3 shrink-0" />
        Specialists ({engineConstraints.length})
        <ChevronDown className={cn('w-3 h-3 transition-transform', showConstraints && 'rotate-180')} />
      </button>
    </div>
  );
}
