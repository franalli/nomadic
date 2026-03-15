'use client';
/**
 * StrategyHeroAccordion
 *
 * Accordion variant of StrategyHero — collapsible inline card.
 * All state is managed by the parent StrategyHero component.
 */

import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Info,
  Sparkles,
} from 'lucide-react';
import Image from 'next/image';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

import {
  formatConstraintRule,
  getConstraintIcon,
  getConstraintSectionLabel,
  getShortConstraintLabel,
  getSummaryBadge,
  renderTopicIcon,
} from './StrategyHeroUtils';

interface StrategyHeroAccordionProps {
  section: StrategySection;
  topic: string;
  topicLabel: string;
  constraints: NonNullable<StrategySection['constraints_applied']>;
  headerId: string;
  contentId: string;
  isAccordionExpanded: boolean;
  specialistColors: { light: string; icon: string };
  isInfeasible: boolean;
  onToggle: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
}

export function StrategyHeroAccordion({
  section,
  topic,
  topicLabel,
  constraints,
  headerId,
  contentId,
  isAccordionExpanded,
  specialistColors,
  isInfeasible,
  onToggle,
  onKeyDown,
}: StrategyHeroAccordionProps) {
  const summaryText = getSummaryBadge(section);

  return (
    <div
      role="region"
      aria-labelledby={headerId}
      data-state={isAccordionExpanded ? 'expanded' : 'collapsed'}
      data-specialist={topic}
      className={cn(
        'w-full rounded-xl mb-4 overflow-hidden',
        'transition-all duration-200',
        'bg-zinc-50 border border-zinc-100',
        'dark:bg-white/[0.03] dark:border-white/5',
        isAccordionExpanded ? 'shadow-soft' : 'shadow-card',
        isInfeasible && 'opacity-60'
      )}
    >
      {/* Accordion Header (clickable) */}
      <div
        id={headerId}
        role="button"
        tabIndex={0}
        aria-expanded={isAccordionExpanded}
        aria-controls={contentId}
        onClick={onToggle}
        onKeyDown={onKeyDown}
        className={cn(
          'flex items-center gap-2 p-3 cursor-pointer min-h-[60px]',
          'transition-all duration-150',
          'hover:bg-zinc-100/50 dark:hover:bg-white/[0.02]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2',
          isAccordionExpanded && ['border-b border-zinc-100 dark:border-white/5', 'bg-zinc-100/50 dark:bg-white/[0.02]']
        )}
      >
        <div className={cn('w-8 h-8 rounded-full flex items-center justify-center shrink-0', specialistColors.light, 'dark:bg-white/10')}>
          {renderTopicIcon(topic, cn('w-4 h-4', specialistColors.icon))}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-zinc-900 dark:text-white leading-tight">{topicLabel}</span>
            {isInfeasible && <span className={`px-1.5 py-0.5 rounded ${DS.textSize.nano} font-bold bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400`}>Unavailable</span>}
            {!isInfeasible && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />}
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-2">
            {section.one_liner || section.editorial_one_liner || summaryText}
          </p>
        </div>
        <span className={`hidden sm:inline-flex ${DS.textSize.micro} font-medium uppercase tracking-wide px-2 py-0.5 rounded-md bg-zinc-100 text-zinc-500 dark:bg-white/5 dark:text-zinc-400`}>
          {summaryText}
        </span>
        <div className={cn('w-6 h-6 flex items-center justify-center text-zinc-400 dark:text-zinc-500 transition-transform duration-200', isAccordionExpanded && 'rotate-180')}>
          <ChevronDown className="w-4 h-4" />
        </div>
      </div>

      {/* Accordion Content */}
      <div
        id={contentId}
        aria-hidden={!isAccordionExpanded}
        className={cn(
          'overflow-hidden transition-all duration-300 ease-out accordion-scrollbar',
          !isAccordionExpanded && 'max-h-0 opacity-0',
          isAccordionExpanded && 'max-h-[300px] opacity-100 overflow-y-auto'
        )}
      >
        <div className={cn('p-4 space-y-4 transform transition-all duration-200 delay-100', !isAccordionExpanded && '-translate-y-2', isAccordionExpanded && 'translate-y-0')}>
          {(section.one_liner || section.editorial_one_liner) && (
            <div className="space-y-1">
              <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}><Sparkles className="w-3 h-3" />Strategy Logic</h4>
              <p className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">{section.one_liner || section.editorial_one_liner}</p>
            </div>
          )}
          {constraints.length > 0 && (
            <div className="space-y-2">
              <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}><AlertCircle className="w-3 h-3" />{getConstraintSectionLabel(topic)}</h4>
              <div className="flex flex-wrap gap-1.5">
                {constraints.map((c, i) => (
                  <span key={i} className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-md', `${DS.textSize.mini} font-medium`,
                    c.type === 'safety' || c.type?.includes('safety')
                      ? 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-700/50'
                      : 'bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-700/50'
                  )} title={c.reason || formatConstraintRule(c.rule)}>
                    {getConstraintIcon(c.type)}{getShortConstraintLabel(c.rule)}
                  </span>
                ))}
              </div>
            </div>
          )}
          {(() => {
            const uniquePrinciples = section.principles?.filter(p => p !== section.one_liner && p !== section.editorial_one_liner && !constraints.some(c => c.reason === p)) || [];
            return uniquePrinciples.length > 0 && (
              <div className="space-y-2">
                <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}><Info className="w-3 h-3" />Key Principles</h4>
                <ul className="space-y-1.5">
                  {uniquePrinciples.slice(0, 4).map((principle, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />{principle}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })()}
          {section.content_added && section.content_added.length > 0 && (
            <div className="space-y-2">
              <h4 className={cn(DS.text.label, 'flex items-center gap-1.5')}><Sparkles className="w-3 h-3" />Recommendations</h4>
              <div className="space-y-2">
                {section.content_added.slice(0, 3).map((item, i) => (
                  <div key={i} className="flex gap-2 items-start p-2 rounded-lg bg-zinc-100/50 dark:bg-white/[0.02] border border-zinc-100 dark:border-white/5">
                    {item.image_url && (
                      <div className="relative w-12 h-12 rounded-md overflow-hidden shrink-0 bg-zinc-200 dark:bg-zinc-800">
                        <Image src={item.image_url} alt={item.title} fill className="object-cover" sizes="48px" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-zinc-900 dark:text-white">{item.title}</p>
                      {item.description && <p className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-1 mt-0.5">{item.description}</p>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {isInfeasible && section.feasibility_reason && (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50">
              <p className="text-sm text-red-700 dark:text-red-400">{section.feasibility_reason}</p>
              {section.alternative_suggestion && <p className="text-xs text-red-600/70 dark:text-red-400/70 mt-1">💡 {section.alternative_suggestion}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
