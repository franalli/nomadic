'use client';
/**
 * S2StrategyStack
 *
 * Stacked specialist agent cards with overflow handling and open-decisions panel.
 * Extracted from S2StrategyView for focused ownership.
 * Used by S2StrategyView in legacy (non-magazine) rendering mode.
 */

import { AlertCircle } from 'lucide-react';
import React from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { OpenDecision, StrategySection } from '@/types/plan-envelope';
import { computeAgentStatus } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { TripHealthBar } from '../TripHealthBar';
import { AgentCard } from './S2AgentCard';
import { DEFAULT_TOPIC_CONFIG, getTopicColorStyle, TOPIC_CONFIG, TOPIC_PRIORITY } from './S2TopicConfig';

// ---------------------------------------------------------------------------
// OpenDecisionsPanel
// ---------------------------------------------------------------------------

export function OpenDecisionsPanel({ decisions }: { decisions: OpenDecision[] }) {
  if (decisions.length === 0) return null;

  const blockingCount = decisions.filter((d) => d.is_blocking).length;

  return (
    <div className="bg-zinc-100 rounded-lg border border-zinc-200 p-4 dark:bg-zinc-900/50 dark:border-zinc-700/30">
      <div className="flex items-center gap-2 mb-3">
        <AlertCircle className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
        <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-200">
          Open decisions
          {blockingCount > 0 && (
            <span className="text-zinc-600 dark:text-zinc-400 ml-1">({blockingCount} blocking)</span>
          )}
        </h3>
      </div>
      <ul className="space-y-2">
        {decisions.slice(0, 4).map((decision) => (
          <li key={decision.id} className="flex items-start gap-2">
            <span
              className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                decision.is_blocking ? 'bg-zinc-900 dark:bg-white' : 'bg-zinc-400 dark:bg-zinc-500'
              }`}
            />
            <span className="text-xs text-zinc-700 dark:text-zinc-300">{decision.statement}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StrategyStack
// ---------------------------------------------------------------------------

interface StrategyStackProps {
  sections: StrategySection[];
  pendingTopics: string[];
  executedTopics: string[];
  tiles?: Record<string, Tile>;
  hasDates?: boolean;
  onOpenActivitySettings?: () => void;
}

export function StrategyStack({
  sections,
  pendingTopics,
  executedTopics,
  tiles = {},
  hasDates = true,
  onOpenActivitySettings,
}: StrategyStackProps) {
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [showAll, setShowAll] = React.useState(false);

  const [isMobile, setIsMobile] = React.useState(false);
  React.useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 1024);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  const generalSection = sections.find((s) => s.specialist_type === 'general');
  const specialistSections = sections.filter((s) => s.specialist_type !== 'general');

  const hasTiles = Object.keys(tiles).length > 0;
  const hasSpecialists = specialistSections.length > 0;

  const filtered = hasSpecialists ? specialistSections : sections;
  const showTripHealth = generalSection && hasTiles;

  const sorted = [...filtered].sort((a, b) => {
    const aIdx = TOPIC_PRIORITY.indexOf(a.specialist_type || 'general');
    const bIdx = TOPIC_PRIORITY.indexOf(b.specialist_type || 'general');
    return aIdx - bIdx;
  });

  const filteredPendingTopics = pendingTopics.filter(
    (topic) => !sorted.some((section) => section.specialist_type === topic)
  );

  const visibleLimit = isMobile ? 1 : 2;
  const visible = showAll ? sorted : sorted.slice(0, visibleLimit);
  const overflow = sorted.length - visibleLimit;
  const useReducedColor = sorted.length > 2;
  const hasPending = filteredPendingTopics.length > 0;

  return (
    <div className="space-y-2" data-reduced-color={useReducedColor}>
      {/* Pending topics placeholder */}
      {filteredPendingTopics.map((topic) => {
        const config = TOPIC_CONFIG[topic] ?? DEFAULT_TOPIC_CONFIG;
        const TopicIcon = config.icon;
        return (
          <div
            key={`pending-${topic}`}
            data-topic={topic}
            style={getTopicColorStyle(topic)}
            className="bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-700 px-4 py-3 topic-border-left"
          >
            <div className="flex items-center gap-2">
              <span className="topic-badge inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium">
                <TopicIcon className="w-3 h-3" />
                {config.label} Specialist
              </span>
              <span className={`${DS.textSize.micro} px-1.5 py-0.5 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded font-medium animate-pulse`}>
                Updating...
              </span>
            </div>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-2">Generating strategy...</p>
          </div>
        );
      })}

      {/* Trip Health Bar (General agent summary — always at top) */}
      {showTripHealth && (
        <TripHealthBar tripSummary={generalSection?.trip_summary} tiles={tiles} />
      )}

      {/* Stacked specialist cards */}
      {visible.length > 0 ? (
        visible.map((section) => {
          const topic = section.specialist_type || 'general';
          const status = computeAgentStatus(topic, pendingTopics, executedTopics);
          return (
            <AgentCard
              key={section.id}
              section={section}
              isExpanded={expandedId === section.id}
              onToggle={() => setExpandedId(expandedId === section.id ? null : section.id)}
              status={status}
              hasDates={hasDates}
              onOpenSettings={onOpenActivitySettings}
            />
          );
        })
      ) : (
        !hasPending && showTripHealth && (
          <div className="text-center py-6 opacity-40">
            <p className="text-xs uppercase tracking-widest text-zinc-500 dark:text-zinc-400">System Ready</p>
            <p className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-400 mt-1`}>
              Add activities like diving or hiking to see specialist logic
            </p>
          </div>
        )
      )}

      {/* Overflow expander */}
      {overflow > 0 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className={cn('text-xs text-emerald-600 dark:text-emerald-400 hover:underline py-1')}
        >
          +{overflow} more specialist{overflow > 1 ? 's' : ''}
        </button>
      )}
    </div>
  );
}
