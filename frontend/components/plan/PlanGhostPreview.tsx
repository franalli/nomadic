'use client';

/**
 * PlanGhostPreview - Static demo preview for the empty plan panel.
 *
 * Shown before the user sends their first message. Communicates what
 * the plan view will look like with realistic demo data (specialist
 * cards, constraint badges, timeline, tiles).
 *
 * Variants:
 *   panel — Desktop right panel: h-full, overflow hidden, gradient fades
 *   page  — Mobile Plan page: min-h-full, natural scroll, inline CTA
 */

import {
  Compass,
  Fish,
  Mountain,
  Palmtree,
  Shield,
  Sparkles,
  Utensils,
} from 'lucide-react';
import { memo } from 'react';

import { motion } from 'framer-motion';

import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface PlanGhostPreviewProps {
  variant?: 'panel' | 'page';
}

// ─────────────────────────────────────────────────────────────────────────────
// Demo Data
// ─────────────────────────────────────────────────────────────────────────────

const DEMO_SPECIALISTS = [
  {
    icon: Fish,
    label: 'Diving',
    color: 'text-sky-500',
    bgColor: 'bg-sky-500/10 dark:bg-sky-500/15',
    oneLiner: 'World-class reef systems with manta ray encounters',
    constraints: ['No-fly 24h after dive', 'Max 3 dives/day'],
  },
  {
    icon: Mountain,
    label: 'Hiking',
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-500/10 dark:bg-emerald-500/15',
    oneLiner: 'Volcanic crater trails through cloud forest',
    constraints: ['Altitude acclimatization'],
  },
];

const DEMO_DAYS = [
  {
    day: 1,
    label: 'Arrive & Settle',
    items: ['Airport transfer', 'Hotel check-in', 'Welcome dinner'],
  },
  {
    day: 2,
    label: 'Morning Dive + Afternoon Hike',
    items: ['Reef dive (2 tanks)', 'Lunch at harbor', 'Crater rim trail'],
  },
  {
    day: 3,
    label: 'Cultural Day',
    items: ['Temple visit', 'Local cooking class', 'Night market'],
  },
];

const DEMO_TILES = [
  { icon: Palmtree, label: 'Flights', value: 'SFO → DPS' },
  { icon: Utensils, label: 'Hotel', value: '4★ beachfront' },
  { icon: Compass, label: 'Duration', value: '7 nights' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function PlanGhostPreviewInner({ variant = 'panel' }: PlanGhostPreviewProps) {
  const isPanel = variant === 'panel';

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.7 }}
      className={cn(
        'relative select-none',
        isPanel
          ? 'h-full overflow-hidden'
          : 'min-h-full overflow-y-auto',
      )}
    >
      {/* Content wrapper — non-interactive */}
      <div className="pointer-events-none p-5 space-y-5">
        {/* Header */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-500" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
              Plan Preview
            </span>
          </div>
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-white">
            Your trip will appear here
          </h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Tell us where you want to go — we&apos;ll build a plan with specialist insights, logistics, and a day-by-day itinerary.
          </p>
        </div>

        {/* Quick Tiles */}
        <div className="flex gap-2">
          {DEMO_TILES.map((tile) => (
            <div
              key={tile.label}
              className={cn(
                'flex-1 flex items-center gap-2 px-3 py-2.5 rounded-xl',
                'bg-zinc-100 dark:bg-white/5',
                'border border-zinc-200 dark:border-white/10',
              )}
            >
              <tile.icon className="w-3.5 h-3.5 text-zinc-400 dark:text-zinc-500 shrink-0" />
              <div className="min-w-0">
                <p className="text-[10px] text-zinc-400 dark:text-zinc-500 font-medium">{tile.label}</p>
                <p className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 truncate">{tile.value}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Specialist Cards */}
        <div className="space-y-3">
          <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
            Specialist Insights
          </h3>
          {DEMO_SPECIALISTS.map((spec) => (
            <div
              key={spec.label}
              className={cn(
                'rounded-xl p-3.5',
                'bg-white dark:bg-white/5',
                'border border-zinc-200 dark:border-white/10',
                'shadow-sm dark:shadow-none',
              )}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <div className={cn('w-6 h-6 rounded-lg flex items-center justify-center', spec.bgColor)}>
                  <spec.icon className={cn('w-3.5 h-3.5', spec.color)} />
                </div>
                <span className="text-sm font-semibold text-zinc-900 dark:text-white">
                  {spec.label}
                </span>
              </div>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-2">
                {spec.oneLiner}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {spec.constraints.map((c) => (
                  <span
                    key={c}
                    className={cn(
                      'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium',
                      'bg-emerald-100 dark:bg-emerald-900/30',
                      'text-emerald-700 dark:text-emerald-400',
                    )}
                  >
                    <Shield className="w-2.5 h-2.5" />
                    {c}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Timeline Preview */}
        <div className="space-y-3">
          <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
            Day-by-Day
          </h3>
          {DEMO_DAYS.map((day) => (
            <div key={day.day} className="flex gap-3">
              {/* Day number pill */}
              <div className="flex flex-col items-center">
                <div className={cn(
                  'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0',
                  'bg-zinc-900 text-white dark:bg-white dark:text-black',
                )}>
                  {day.day}
                </div>
                {day.day < DEMO_DAYS.length && (
                  <div className="w-px flex-1 bg-zinc-200 dark:bg-white/10 mt-1" />
                )}
              </div>
              {/* Day content */}
              <div className="pb-4 min-w-0 flex-1">
                <p className="text-sm font-semibold text-zinc-900 dark:text-white mb-1">
                  {day.label}
                </p>
                <div className="space-y-1">
                  {day.items.map((item) => (
                    <p key={item} className="text-xs text-zinc-500 dark:text-zinc-400">
                      {item}
                    </p>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Inline CTA (mobile page variant) */}
        {!isPanel && (
          <div className="text-center py-6">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Start a conversation to build your plan
            </p>
          </div>
        )}
      </div>

      {/* Panel variant: gradient overlays + floating CTA */}
      {isPanel && (
        <>
          {/* Top fade */}
          <div
            className="absolute inset-x-0 top-0 h-12 pointer-events-none"
            style={{
              background: 'linear-gradient(to bottom, var(--theme-panel), transparent)',
            }}
          />
          {/* Bottom fade + CTA */}
          <div
            className="absolute inset-x-0 bottom-0 pointer-events-none"
            style={{
              background: 'linear-gradient(to top, var(--theme-panel) 30%, transparent)',
            }}
          >
            <div className="flex items-center justify-center h-24">
              <p className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
                Start a conversation to build your plan
              </p>
            </div>
          </div>
        </>
      )}
    </motion.div>
  );
}

export const PlanGhostPreview = memo(PlanGhostPreviewInner);
