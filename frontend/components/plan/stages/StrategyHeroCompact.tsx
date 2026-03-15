'use client';

import { ChevronRight } from 'lucide-react';
import Image from 'next/image';

import { BottomSheet } from '@/components/ui/bottom-sheet';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { StrategySection } from '@/types/plan-envelope';

import { CompactSheetContent } from './StrategyHeroCompactSheet';
import { renderTopicIcon } from './StrategyHeroUtils';

interface StrategyHeroCompactProps {
  section: StrategySection;
  displaySection: StrategySection;
  topic: string;
  topicLabel: string;
  heroImage: string;
  constraints: NonNullable<StrategySection['constraints_applied']>;
  constraintCount: number;
  isInfeasible: boolean;
  isSheetOpen: boolean;
  onSheetOpenChange: (open: boolean) => void;
  onExpand: () => void;
  shouldShowEnrichmentNotice: boolean;
  enrichmentUiState: string;
  enrichmentErrorLabel: string;
  onRetryEnrichment: () => void;
}

export function StrategyHeroCompact({
  section,
  displaySection,
  topic,
  topicLabel,
  heroImage,
  constraints,
  constraintCount,
  isInfeasible,
  isSheetOpen,
  onSheetOpenChange,
  onExpand,
  shouldShowEnrichmentNotice,
  enrichmentUiState,
  enrichmentErrorLabel,
  onRetryEnrichment,
}: StrategyHeroCompactProps) {
  const summary =
    section.one_liner ||
    section.editorial_one_liner ||
    (section.principles?.length > 0 ? section.principles[0] : null) ||
    (constraintCount > 0 ? `${constraintCount} constraint${constraintCount > 1 ? 's' : ''} active` : null) ||
    section.subtitle ||
    'Tap to view details';

  return (
    <>
      <button
        type="button"
        onClick={onExpand}
        className={cn(
          'group mb-4 flex w-full items-center gap-2 rounded-xl border p-3 text-left transition-all',
          'bg-zinc-50 dark:bg-white/5 border-zinc-200 dark:border-white/10',
          'hover:border-zinc-300 dark:hover:border-white/20',
          'hover:bg-zinc-100 dark:hover:bg-white/10',
          'hover:shadow-card active:scale-[0.995]',
          isInfeasible && 'opacity-60'
        )}
      >
        <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-zinc-200 dark:bg-zinc-800">
          <Image src={heroImage} alt={section.title} fill className="object-cover" sizes="40px" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {renderTopicIcon(topic, 'h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400')}
            <span className="truncate text-xs font-bold text-zinc-900 dark:text-white">
              {topicLabel}
            </span>
            {!isInfeasible && <span className="text-xs text-emerald-600 dark:text-emerald-400">✓</span>}
            {isInfeasible && (
              <span
                className={cn(
                  'rounded px-1.5 py-0.5 font-bold bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
                  DS.textSize.nano
                )}
              >
                Unavailable
              </span>
            )}
            {constraintCount > 0 && !isInfeasible && (
              <span
                className={cn(
                  'rounded-full bg-amber-100 px-1.5 py-0.5 font-bold text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
                  DS.textSize.nano
                )}
              >
                {constraintCount} {constraintCount === 1 ? 'Rule' : 'Rules'}
              </span>
            )}
          </div>
          <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400 group-hover:text-zinc-700 dark:group-hover:text-zinc-300">
            {summary}
          </p>
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400 transition-colors group-hover:text-zinc-600 dark:text-zinc-500 dark:group-hover:text-zinc-300" />
      </button>

      <BottomSheet
        open={isSheetOpen}
        onOpenChange={onSheetOpenChange}
        title={`${topicLabel} Strategy`}
        hint="Tap outside to close"
      >
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
          <CompactSheetContent section={displaySection} constraints={constraints} />
        </div>
      </BottomSheet>
    </>
  );
}
