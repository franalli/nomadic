'use client';
/** S2AgentCard — single specialist agent card with topic color system and expandable detail panel. */

import { ChevronDown, Lightbulb, Settings } from 'lucide-react';
import React from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { AgentStatus, StrategySection } from '@/types/plan-envelope';

import { S2AgentCardExpanded } from './S2AgentCardExpanded';
import { DEFAULT_TOPIC_CONFIG, getTopicColorStyle, RichText, TOPIC_CONFIG } from './S2TopicConfig';

interface AgentCardProps {
  section: StrategySection;
  isExpanded: boolean;
  onToggle: () => void;
  status: AgentStatus;
  hasDates?: boolean;
  onOpenSettings?: () => void;
}

export function AgentCard({ section, isExpanded, onToggle, status, hasDates = true, onOpenSettings }: AgentCardProps) {
  const cardRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (isExpanded && cardRef.current) {
      const timer = setTimeout(() => { cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, 50);
      return () => clearTimeout(timer);
    }
  }, [isExpanded]);

  const oneLiner = section.one_liner || section.bullets[0] || '';
  const principles = section.principles && section.principles.length > 0 ? section.principles : section.bullets.slice(0, 3);
  const topic = section.specialist_type || 'general';
  const config = TOPIC_CONFIG[topic] ?? DEFAULT_TOPIC_CONFIG;
  const Icon = config.icon;
  const isInfeasible = section.feasibility_status === 'infeasible';
  const hasCaveat = section.feasibility_status === 'caveat';

  return (
    <div ref={cardRef} data-topic={topic} style={getTopicColorStyle(topic)}
      className={cn('rounded-2xl border overflow-hidden topic-border-left transition-all duration-200', 'bg-white shadow-card', 'dark:bg-zinc-900 dark:shadow-none',
        isInfeasible && 'border-red-500/50 bg-red-950/10',
        hasCaveat && 'border-zinc-400/30',
        !isInfeasible && !hasCaveat && 'border-zinc-200 hover:border-emerald-500/30 hover:shadow-soft dark:border-zinc-800')}>
      <button onClick={onToggle}
        aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${section.title ?? 'strategy'} details`}
        className={cn('w-full px-5 py-4 text-left transition-all duration-200 group',
          isInfeasible ? 'bg-red-950/20 hover:bg-red-950/30' : 'topic-header-tint hover:bg-zinc-50 dark:hover:bg-muted/30',
          'active:scale-[0.995]')}>
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2">
            <span className={cn('inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium', isInfeasible ? 'bg-red-500/20 text-red-400' : 'topic-badge')}>
              <Icon className="w-3 h-3" />{config.label} Specialist
            </span>
            {isInfeasible && <span className={`${DS.textSize.micro} px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded font-medium uppercase tracking-wider`}>Unavailable</span>}
            {hasCaveat && <span className={`${DS.textSize.micro} px-1.5 py-0.5 bg-zinc-500/20 text-zinc-400 rounded font-medium`}>Limited</span>}
            {!isInfeasible && status !== 'ready' && (
              <span className={cn(`${DS.textSize.micro} px-2 py-1 rounded-full font-bold uppercase tracking-wide`,
                status === 'updating' && 'bg-emerald-50 text-emerald-700 border border-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-transparent animate-pulse',
                status === 'needs_input' && 'bg-zinc-100 text-zinc-500 dark:bg-muted dark:text-muted-foreground')}>
                {status === 'updating' ? 'Updating...' : 'Needs input'}
              </span>
            )}
          </div>
          {!isInfeasible && (
            <div className="flex items-center gap-1.5">
              {onOpenSettings && ['diving', 'hiking', 'skiing', 'cycling', 'sailing'].includes(topic) && (
                <div role="button" tabIndex={0}
                  onClick={(e) => { e.stopPropagation(); onOpenSettings(); }}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); onOpenSettings(); } }}
                  className={cn('w-8 h-8 rounded-full flex items-center justify-center shrink-0 cursor-pointer', 'bg-zinc-100 hover:bg-zinc-200 dark:bg-white/5 dark:hover:bg-white/10', 'transition-all duration-200')}
                  title="Activity settings">
                  <Settings className="w-4 h-4 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
                </div>
              )}
              <div className={cn('w-8 h-8 rounded-full flex items-center justify-center shrink-0', 'bg-zinc-50 hover:bg-zinc-100 dark:bg-white/5 dark:hover:bg-white/10', 'transition-all duration-200')}>
                <ChevronDown className={cn('w-4 h-4 transition-transform duration-200', 'text-zinc-400 group-hover:text-emerald-600 dark:group-hover:text-emerald-400', isExpanded && 'rotate-180')} />
              </div>
            </div>
          )}
        </div>

        {isInfeasible && section.feasibility_reason && <div className="mt-2 text-xs text-red-400"><RichText>{section.feasibility_reason}</RichText></div>}
        {isInfeasible && section.alternative_suggestion && <div className={`mt-1 ${DS.textSize.micro} text-muted-foreground`}>💡 <RichText>{section.alternative_suggestion}</RichText></div>}
        {hasCaveat && section.feasibility_reason && (
          <div className="mt-2 text-xs text-zinc-500 flex items-center gap-1"><span>⚠️</span><RichText>{section.feasibility_reason}</RichText></div>
        )}

        {!isInfeasible && status !== 'needs_input' && (
          <div className={`mt-1.5 flex items-center gap-1.5 ${DS.textSize.micro} text-muted-foreground`}>
            <span className="text-emerald-600 dark:text-emerald-400">{status === 'ready' ? '✓' : '○'}</span>
            <span className="text-sm text-zinc-500 dark:text-zinc-400">{status === 'ready' ? config.readyAction : config.updatingAction}</span>
          </div>
        )}
        {!isInfeasible && status === 'ready' && !hasDates && (
          <div className={`mt-1 flex items-center gap-1.5 ${DS.textSize.micro} text-zinc-500`}><span>📅</span><span>Add dates to unlock day-by-day scheduling</span></div>
        )}
        {!isExpanded && !isInfeasible && (
          <p className={`mt-2 ${DS.textSize.micro} font-medium text-emerald-600 dark:text-emerald-400 opacity-0 group-hover:opacity-100 transition-opacity`}>
            Tap to see expert details →
          </p>
        )}

        {!isExpanded && !isInfeasible && (
          <div className="mt-2 w-full">
            {oneLiner && <p className="text-xs text-muted-foreground mb-2"><RichText>{oneLiner}</RichText></p>}
            {principles.length > 0 && (
              <div className="mt-3 space-y-2">
                {principles.slice(0, 4).map((p, i) => (
                  <div key={i} className={cn('flex items-start gap-3 p-2 rounded-lg transition-colors', 'hover:bg-zinc-50', 'dark:hover:bg-zinc-800/30')}>
                    <Lightbulb className="w-3.5 h-3.5 mt-0.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                    <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400 font-medium">{p}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </button>

      {isExpanded && !isInfeasible && <S2AgentCardExpanded section={section} />}
    </div>
  );
}
