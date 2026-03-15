'use client';

import { Sparkles } from 'lucide-react';
import Image from 'next/image';

import { BottomSheet } from '@/components/ui/bottom-sheet';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

import { HeroSheetContent } from './StrategyHeroHeroSheet';
import {
  formatConstraintRule,
  getConstraintIcon,
  getShortConstraintLabel,
  renderTopicIcon,
} from './StrategyHeroUtils';

// =============================================================================
// Types
// =============================================================================

export interface StrategyHeroContentProps {
  section: StrategySection;
  displaySection: StrategySection;
  topic: string;
  topicLabel: string;
  heroImage: string;
  constraints: NonNullable<StrategySection['constraints_applied']>;
  isInfeasible: boolean;
  isSheetOpen: boolean;
  onSheetOpenChange: (open: boolean) => void;
  onExpand: () => void;
  /** Enrichment UI state for local_expert */
  shouldShowEnrichmentNotice: boolean;
  enrichmentUiState: string;
  enrichmentErrorLabel: string;
  onRetryEnrichment: () => void;
}

// =============================================================================
// Component — Hero mode (Magazine Style)
// =============================================================================

export function StrategyHeroContent({
  section,
  displaySection,
  topic,
  topicLabel,
  heroImage,
  constraints,
  isInfeasible,
  isSheetOpen,
  onSheetOpenChange,
  onExpand,
  shouldShowEnrichmentNotice,
  enrichmentUiState,
  enrichmentErrorLabel,
  onRetryEnrichment,
}: StrategyHeroContentProps) {
  return (
    <>
    <button
      type="button"
      onClick={onExpand}
      className={cn(
        'relative w-full rounded-2xl overflow-hidden shadow-card group mb-6 text-left',
        'cursor-pointer transition-all',
        'hover:shadow-soft hover:scale-[1.01] active:scale-[0.995]',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2',
        isInfeasible && 'opacity-70'
      )}
    >
      {/* Background Image - FIXED HEIGHT to prevent giant images */}
      {/* Mobile: h-56 (224px), Desktop: h-72 (288px) - max ~30% viewport */}
      <div className="relative h-56 md:h-72 w-full">
        <Image src={heroImage} alt={section.title} fill className="object-cover transition-transform duration-700 group-hover:scale-105" priority sizes="(max-width: 768px) 100vw, 800px" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent" />
      </div>
      {/* Content Overlay */}
      <div className="absolute inset-0 p-5 md:p-6 flex flex-col justify-end">
        <div className="mb-2">
          <span className={cn(`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md ${DS.textSize.micro} font-bold uppercase tracking-widest`, 'bg-white/20 backdrop-blur-md text-white border border-white/20')}>
            {renderTopicIcon(topic, "w-3 h-3")}{topicLabel} Strategy
          </span>
          {isInfeasible && <span className={`ml-2 px-2 py-1 rounded-md ${DS.textSize.micro} font-bold bg-red-500/80 text-white`}>Unavailable</span>}
        </div>
        <h1 className="text-xl md:text-2xl lg:text-3xl font-bold text-white mb-2 leading-tight">{section.title}</h1>
        <p className="text-white/80 text-sm md:text-base line-clamp-2 max-w-xl mb-4">{section.one_liner || section.subtitle}</p>
        {isInfeasible && section.feasibility_reason && <p className="text-red-300 text-sm mb-4">{section.feasibility_reason}</p>}
        {isInfeasible && section.alternative_suggestion && <p className="text-white/60 text-xs mb-4">💡 {section.alternative_suggestion}</p>}
        {/* Constraint Pills (Horizontal Scroll) */}
        {constraints.length > 0 && !isInfeasible && (
          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar -mx-5 md:-mx-6 px-5 md:px-6 pb-1">
            {constraints.map((c, i) => (
              <div key={i} className={cn('flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg shrink-0', 'bg-black/40 backdrop-blur-md border border-white/10')} title={c.reason || formatConstraintRule(c.rule)}>
                {getConstraintIcon(c.type)}
                <span className="text-xs font-medium text-white/90">{getShortConstraintLabel(c.rule)}</span>
              </div>
            ))}
          </div>
        )}
        {/* Principles (if no constraints) */}
        {constraints.length === 0 && section.principles.length > 0 && !isInfeasible && (
          <div className="flex flex-wrap gap-2">
            {section.principles.slice(0, 3).map((principle, i) => (
              <div key={i} className={cn('flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg', 'bg-black/40 backdrop-blur-md border border-white/10')}>
                <Sparkles className="w-3 h-3 text-emerald-400" />
                <span className="text-xs font-medium text-white/90 line-clamp-1">{principle}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </button>
    <BottomSheet open={isSheetOpen} onOpenChange={onSheetOpenChange} title={`${topicLabel} Strategy`} hint="Tap to expand">
      <div className="space-y-6 pb-24">
        {shouldShowEnrichmentNotice && (
          <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-300">
            {(enrichmentUiState === 'loading' || enrichmentUiState === 'pending') && (
              <p>Loading local travel intelligence...</p>
            )}
            {enrichmentUiState === 'failed' && (
              <div className="flex items-center justify-between gap-3">
                <p>{enrichmentErrorLabel}</p>
                <button
                  type="button"
                  onClick={onRetryEnrichment}
                  className="shrink-0 rounded-md border border-zinc-300 px-2 py-1 text-xs font-semibold text-zinc-800 hover:bg-zinc-100 dark:border-zinc-600 dark:text-zinc-100 dark:hover:bg-zinc-800"
                >
                  Retry
                </button>
              </div>
            )}
          </div>
        )}
        <HeroSheetContent section={displaySection} constraints={constraints} heroImage={heroImage} />
      </div>
    </BottomSheet>
    </>
  );
}
