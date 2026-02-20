'use client';

import { AlertTriangle, CheckCircle, ChevronDown, Clock, Shield } from 'lucide-react';
import type { ReactNode } from 'react';

import { NICHE_SPECIALIST_IDS } from '@/lib/specialists';
import { cn } from '@/lib/utils';
import type { PlanViewModel } from '@/types/plan-envelope';

import { getShortConstraintLabel } from './stages/StrategyHero';

interface StrategyConstraintBarProps {
  fullModeSections: PlanViewModel['strategy_sections'];
  validatedRules: Set<string>;
  violatedRules: Set<string>;
  hasItineraryContent: boolean;
  showConstraints: boolean;
  onToggleConstraints: () => void;
  stayCount?: number;
  staysExpanded?: boolean;
  onToggleStays?: () => void;
}

/** Trip DNA constraint pill bar — shows engine constraints with validation state. */
export function StrategyConstraintBar({
  fullModeSections,
  validatedRules,
  violatedRules,
  hasItineraryContent,
  showConstraints,
  onToggleConstraints,
  stayCount = 0,
  staysExpanded = false,
  onToggleStays,
}: StrategyConstraintBarProps): ReactNode {
  // Filter: only niche specialists, not local_expert/general
  // Exclude soft/info severity — only show blocking + strong constraints
  const engineConstraints = (fullModeSections ?? [])
    .filter((s) => NICHE_SPECIALIST_IDS.includes(s.specialist_type || ''))
    .flatMap((s) => s.constraints_applied || [])
    .filter((c) => {
      const sev = (c as Record<string, string>).severity;
      return !sev || sev === 'blocking' || sev === 'strong';
    });

  if (engineConstraints.length === 0 && stayCount === 0) return null;

  const getShortLabel = (c: { label?: string; rule?: string; reason?: string }) =>
    c.label ||
    (c.rule ? getShortConstraintLabel(c.rule) : null) ||
    'Constraint';

  const getPillStyle = (c: { rule?: string; type?: string; reason?: string }) => {
    const rule = c.rule;
    const isViolated =
      rule &&
      (violatedRules.has(rule) ||
        [...violatedRules].some((vr) => vr?.includes(rule) || rule.includes(vr || '')));
    const isValidated =
      rule &&
      (validatedRules.has(rule) ||
        [...validatedRules].some((vr) => vr?.includes(rule) || rule.includes(vr || '')));

    if (isViolated) {
      return {
        pillClass:
          'bg-amber-50 dark:bg-amber-900/30 border-amber-400 dark:border-amber-500/60 ring-2 ring-amber-400/60',
        Icon: AlertTriangle,
      };
    }
    if (isValidated) {
      return {
        pillClass:
          'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-600/50',
        Icon: CheckCircle,
      };
    }
    const t = `${c.type || ''} ${c.rule || ''} ${c.reason || ''}`.toLowerCase();
    const blocking = [
      'no_fly','no-fly','nofly','safety','altitude','buffer','24h','24 hour',
      'diving','dive','scuba','decompression','fly','flight',
    ];
    const strong = ['morning','footwear','gear','timing','equipment','certification'];
    if (blocking.some((k) => t.includes(k))) {
      return {
        pillClass:
          'border-red-500/40 bg-red-500/10 text-red-600 dark:border-red-500/40 dark:bg-red-500/15 dark:text-red-300',
        Icon: Shield,
      };
    }
    if (strong.some((k) => t.includes(k))) {
      return {
        pillClass:
          'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:border-amber-500/40 dark:bg-amber-500/15 dark:text-amber-300',
        Icon: Shield,
      };
    }
    return {
      pillClass:
        'border-zinc-400/40 bg-zinc-500/10 text-zinc-600 dark:border-zinc-500/40 dark:bg-zinc-500/15 dark:text-zinc-400',
      Icon: Shield,
    };
  };

  return (
    <div className="flex items-center gap-2 px-4 py-2 flex-wrap">
      {engineConstraints.map((c, i) => {
        const style = getPillStyle(c);
        const t = `${c.type || ''} ${c.rule || ''} ${c.reason || ''}`.toLowerCase();
        const blocking = [
          'no_fly','no-fly','nofly','safety','altitude','buffer','24h','24 hour',
          'diving','dive','scuba','decompression','fly','flight',
        ];
        const strong = ['morning','footwear','gear','timing','equipment','certification'];
        const IconEl = blocking.some((k) => t.includes(k))
          ? AlertTriangle
          : strong.some((k) => t.includes(k))
          ? Clock
          : Shield;
        return (
          <span
            key={`${c.rule}-${i}`}
            title={c.reason || c.rule?.replace(/_/g, ' ')}
            className={cn(
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium whitespace-nowrap',
              style.pillClass
            )}
          >
            <IconEl className="w-3.5 h-3.5 shrink-0" />
            <span>{getShortLabel(c)}</span>
          </span>
        );
      })}
      {stayCount > 0 && onToggleStays && (
        <>
          {engineConstraints.length > 0 && (
            <span className="w-1 h-1 rounded-full bg-zinc-500/50 shrink-0" />
          )}
          <button
            type="button"
            onClick={onToggleStays}
            className={cn(
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium whitespace-nowrap transition-colors',
              'border-zinc-300 dark:border-white/10 bg-zinc-100 dark:bg-white/[0.06]',
              'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-white/10',
            )}
          >
            🏨 Stays ({stayCount})
            <ChevronDown className={cn('w-3 h-3 transition-transform', staysExpanded && 'rotate-180')} />
          </button>
        </>
      )}
      {hasItineraryContent && engineConstraints.length > 0 && (
        <button
          type="button"
          onClick={onToggleConstraints}
          className={cn(
            'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap transition-colors',
            'text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-white/[0.06] dark:hover:text-white',
          )}
        >
          Specialists
          <ChevronDown className={cn('w-3 h-3 transition-transform', showConstraints && 'rotate-180')} />
        </button>
      )}
    </div>
  );
}
