'use client';
/**
 * S2StrategyView
 *
 * Strategy ready state — shows stacked agent cards (one per topic) with color-coded UI.
 * This is the main planning view before itinerary generation.
 *
 * NOTE: This component renders CONTENT ONLY.
 * Header and CTAs are owned by StrategyStageRenderer.
 *
 * Agent status is COMPUTED from pending/executed topics, not stored on section.
 */

import { ChevronUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import {
  type PlanViewModel,
} from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import type { DataDensity } from '../StrategyStageRenderer';
import { OpenDecisionsPanel, StrategyStack } from './S2StrategyStack';
import { DEFAULT_TOPIC_CONFIG, TOPIC_CONFIG } from './S2TopicConfig';
import { StrategyHero } from './StrategyHero';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface S2StrategyViewProps {
  viewModel: PlanViewModel;
  onRefineAssumptions?: () => void;
  /** Topics pending execution (for "Updating..." state) */
  pendingTopics?: string[];
  /** Topics that have been executed (from viewModel.executed_strategy_topics) */
  executedTopics?: string[];
  /** Tiles for TripHealthBar inventory counts */
  tiles?: Record<string, Tile>;
  /** Trip inputs for reactivity (store subscription provides live updates) */
  tripInputs?: DocumentTripInputs;
  /**
   * Data density level for adaptive rendering.
   * - 'bridge' / 'ghost': Use Accordion mode (collapsible inline)
   * - 'full': Use Compact mode (Trip DNA Bar)
   * - 'empty': Cards not rendered (handled by parent)
   * @see docs/ux_unified_architecture.md Section XII
   */
  density?: DataDensity;
  /**
   * Specialist type to expand (for chat-triggered expansion).
   * When this value changes to a valid specialist type, that card will be expanded.
   * Set to null/undefined to not trigger expansion.
   */
  expandSpecialistType?: string | null;
  /**
   * Whether to auto-expand cards on first load (3s preview then collapse).
   * - true (default for 'bridge'): Cards expand briefly then collapse
   * - false (default for 'ghost'): Cards stay collapsed
   * @default true for bridge density, false for ghost density
   */
  autoExpandOnLoad?: boolean;
  /** Callback to open activity settings sheet (for specialist gear icons) */
  onOpenActivitySettings?: () => void;
}

// ---------------------------------------------------------------------------
// S2StrategyView — Main export
// ---------------------------------------------------------------------------

export function S2StrategyView({
  viewModel,
  onRefineAssumptions,
  pendingTopics = [],
  executedTopics,
  tiles = {},
  tripInputs: propTripInputs,
  density,
  expandSpecialistType,
  autoExpandOnLoad,
  onOpenActivitySettings,
}: S2StrategyViewProps) {
  // FIX: Use store values with prop fallback for reactivity
  const tripInputs = useTripInputsWithFallback(propTripInputs);

  const { strategy_sections: rawStrategySections = [], open_decisions = [] } = viewModel;

  // Filter out domain specialists with no content (e.g., skiing in tropical destinations)
  // General/local_expert always show; domain specialists need content_added to be visible
  const strategy_sections = rawStrategySections.filter((section) => {
    const isGeneralType = ['general', 'local_expert'].includes(section.specialist_type || '');
    if (isGeneralType) return true;
    return section.content_added && section.content_added.length > 0;
  });

  // Use viewModel's executed_strategy_topics if not provided via props
  const resolvedExecutedTopics = executedTopics ?? viewModel.executed_strategy_topics ?? [];

  // Check if dates are set
  const hasDates = Boolean(tripInputs?.start_date && tripInputs?.end_date);

  // Compute variant from density
  const variant = density === 'full' ? 'compact' : (density === 'bridge' || density === 'ghost') ? 'accordion' : 'hero';

  // Determine auto-expand behavior based on density if not explicitly set
  const shouldAutoExpand = autoExpandOnLoad ?? (density === 'bridge');

  // Use Magazine-style rendering when density is provided (new architecture)
  const useMagazineStyle = density !== undefined;

  // =========================================================================
  // ACCORDION STATE MANAGEMENT (for Bridge Mode)
  // All hooks MUST be called unconditionally before any early return
  // =========================================================================

  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [hasShownPreview, setHasShownPreview] = useState(false);
  const expandedCount = expandedIds.size;

  // Staggered auto-expand on first load — only for PLAN mode (bridge density)
  useEffect(() => {
    if (variant === 'accordion' && strategy_sections.length > 0 && !hasShownPreview && shouldAutoExpand) {
      setHasShownPreview(true);

      const EXPAND_DURATION = 2500;
      const STAGGER_DELAY = 500;
      const CARD_CYCLE = EXPAND_DURATION + STAGGER_DELAY;
      const timeoutIds: NodeJS.Timeout[] = [];

      strategy_sections.forEach((section, index) => {
        const expandAt = index * CARD_CYCLE;
        const collapseAt = expandAt + EXPAND_DURATION;

        const expandTimer = setTimeout(() => {
          setExpandedIds((prev) => { const next = new Set(prev); next.add(section.id); return next; });
        }, expandAt);
        timeoutIds.push(expandTimer);

        const collapseTimer = setTimeout(() => {
          setExpandedIds((prev) => { const next = new Set(prev); next.delete(section.id); return next; });
        }, collapseAt);
        timeoutIds.push(collapseTimer);
      });

      return () => { timeoutIds.forEach((id) => clearTimeout(id)); };
    }
  }, [variant, strategy_sections, hasShownPreview, shouldAutoExpand]);

  // Chat-triggered expansion: expand a specific specialist card
  useEffect(() => {
    let scrollTimer: ReturnType<typeof setTimeout> | null = null;

    if (expandSpecialistType && variant === 'accordion') {
      const section = strategy_sections.find((s) => s.specialist_type === expandSpecialistType);
      if (section) {
        setExpandedIds((prev) => { const next = new Set(prev); next.add(section.id); return next; });

        scrollTimer = setTimeout(() => {
          const card = document.querySelector(`[data-specialist="${expandSpecialistType}"]`);
          if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
      }
    }

    return () => { if (scrollTimer) clearTimeout(scrollTimer); };
  }, [expandSpecialistType, variant, strategy_sections]);

  const handleExpandChange = useCallback((sectionId: string, expanded: boolean) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (expanded) { next.add(sectionId); } else { next.delete(sectionId); }
      return next;
    });
  }, []);

  const handleCollapseAll = useCallback(() => { setExpandedIds(new Set()); }, []);

  // NOTE: Early return MUST come AFTER all hooks
  if (strategy_sections.length === 0 && pendingTopics.length === 0) {
    return null;
  }

  return (
    <div className={cn('flex flex-col', useMagazineStyle ? 'gap-2' : 'p-[clamp(8px,1vw,16px)] space-y-[clamp(8px,1vw,16px)]')}>
      {useMagazineStyle ? (
        <>
          {/* Collapse All button (shown when 2+ accordion cards are expanded) */}
          {variant === 'accordion' && expandedCount >= 2 && (
            <div className="flex justify-end mb-1">
              <button
                onClick={handleCollapseAll}
                className={cn(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md',
                  `${DS.textSize.micro} font-bold uppercase tracking-wider`,
                  'text-zinc-500 hover:text-zinc-900',
                  'dark:text-zinc-400 dark:hover:text-white',
                  'bg-zinc-100 hover:bg-zinc-200',
                  'dark:bg-white/5 dark:hover:bg-white/10',
                  'transition-colors duration-150'
                )}
              >
                <ChevronUp className="w-3 h-3" />
                Collapse All
              </button>
            </div>
          )}

          {/* Magazine Style: StrategyHero cards */}
          {strategy_sections.map((section) => (
            <StrategyHero
              key={section.id}
              section={section}
              variant={variant}
              isExpanded={variant === 'accordion' ? expandedIds.has(section.id) : undefined}
              onExpandChange={variant === 'accordion' ? (expanded) => handleExpandChange(section.id, expanded) : undefined}
            />
          ))}

          {/* Pending topics placeholder */}
          {pendingTopics.map((topic) => {
            const config = TOPIC_CONFIG[topic] ?? DEFAULT_TOPIC_CONFIG;
            const TopicIcon = config.icon;
            return (
              <div
                key={`pending-${topic}`}
                className="flex items-center gap-3 p-3 rounded-xl bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 animate-pulse"
              >
                <div className="w-10 h-10 rounded-lg bg-zinc-200 dark:bg-zinc-700 flex items-center justify-center">
                  <TopicIcon className="w-4 h-4 text-zinc-400" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-zinc-500">{config.label}</span>
                    <span className={`${DS.textSize.micro} px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 font-medium`}>
                      Loading...
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-0.5">Generating strategy...</p>
                </div>
              </div>
            );
          })}
        </>
      ) : (
        <>
          {/* Legacy: Strategy stack — TripHealthBar (General) + Specialist cards */}
          <StrategyStack
            sections={strategy_sections}
            pendingTopics={pendingTopics}
            executedTopics={resolvedExecutedTopics}
            tiles={tiles}
            hasDates={hasDates}
            onOpenActivitySettings={onOpenActivitySettings}
          />
        </>
      )}

      {/* Open decisions panel */}
      <OpenDecisionsPanel decisions={open_decisions} />

      {/* Secondary action — refine assumptions (optional) */}
      {onRefineAssumptions && (
        <button
          onClick={onRefineAssumptions}
          className="w-full py-2 px-4 rounded-lg text-sm text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
        >
          Refine assumptions
        </button>
      )}
    </div>
  );
}

export default S2StrategyView;
