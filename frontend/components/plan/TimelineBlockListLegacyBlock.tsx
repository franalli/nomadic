'use client';

import { AlertTriangle } from 'lucide-react';
import { createElement } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/state/uiStore';
import type { DayBlock } from '@/types/plan-envelope';

import { getTopicLabel } from './stages/StrategyHeroUtils';
import { getIconForBlock } from './TimelineBlockList.helpers';

interface TimelineBlockListLegacyBlockProps {
  block: DayBlock;
  blockId: string;
  activeBlockId?: string | null;
  showPriceEstimates: boolean;
}

export function TimelineBlockListLegacyBlock({
  block,
  blockId,
  activeBlockId,
  showPriceEstimates,
}: TimelineBlockListLegacyBlockProps) {
  const blockIcon = getIconForBlock(block);
  const isBlockSafety = block.is_buffer || !!block.buffer_type;
  const isActiveBlock = activeBlockId === blockId;
  const isUnschedulable = block.unschedulable === true;

  return (
    <div
      key={blockId}
      onMouseEnter={() => useUIStore.getState().setHoveredActivityId(blockId)}
      onMouseLeave={() => useUIStore.getState().setHoveredActivityId(null)}
      id={`timeline-item-${blockId}`}
      data-map-id={blockId}
      className={cn(
        'relative rounded-xl border p-4 transition-all',
        isUnschedulable
          ? 'bg-zinc-100/50 border-dashed border-amber-500/50 opacity-60 dark:bg-zinc-900/30'
          : isBlockSafety
            ? 'bg-zinc-500/5 border-zinc-500/20'
            : isActiveBlock
              ? 'scale-[1.02] border-emerald-500/50 bg-white shadow-soft dark:bg-zinc-900'
              : 'bg-white border-zinc-200 hover:border-emerald-500/50 hover:shadow-soft dark:bg-zinc-900 dark:border-white/10'
      )}
    >
      {isUnschedulable && (
        <div className="absolute -top-2 left-3 flex items-center gap-1.5 rounded border border-amber-500/30 bg-amber-500/20 px-2 py-0.5">
          <AlertTriangle className="h-3 w-3 text-amber-500" />
          <span className={cn(DS.textSize.micro, 'font-semibold text-amber-600 dark:text-amber-400')}>
            Cannot schedule
          </span>
        </div>
      )}

      <div className="flex items-start gap-4">
        <div
          className={cn(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-full',
            isUnschedulable
              ? 'bg-amber-500/10 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300'
              : isBlockSafety
                ? 'bg-zinc-500/10 text-zinc-600 dark:bg-zinc-500/15 dark:text-zinc-400'
                : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
          )}
        >
          {isUnschedulable
            ? <AlertTriangle className="h-4 w-4" />
            : createElement(blockIcon, { className: 'h-4 w-4' })}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'text-xs font-medium uppercase tracking-wide',
                isUnschedulable
                  ? 'text-amber-600 dark:text-amber-300'
                  : isBlockSafety
                    ? 'text-zinc-600 dark:text-zinc-400'
                    : 'text-zinc-500 dark:text-zinc-400'
              )}
            >
              {block.period}
            </span>
            {block.intensity && !block.is_buffer && (() => {
              const activityLower = (block.activity_type || '').toLowerCase();
              const summaryLower = (block.summary || '').toLowerCase();
              const isFreeDayBlock = ['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
                (keyword) => activityLower.includes(keyword) || summaryLower.includes(keyword)
              );
              if (isFreeDayBlock) return null;
              return (
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                  {block.intensity}
                </span>
              );
            })()}
            {block.specialist_type && (
              <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                {getTopicLabel(block.specialist_type)}
              </span>
            )}
          </div>

          <p
            className={cn(
              'mt-1 font-medium',
              isUnschedulable
                ? 'line-through text-zinc-500 dark:text-zinc-400'
                : isBlockSafety
                  ? 'text-zinc-600 dark:text-zinc-400'
                  : 'text-zinc-900 dark:text-white'
            )}
          >
            {block.activity_type || block.summary}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">
            {block.summary}
          </p>

          {isUnschedulable && block.unschedulable_reason && (
            <p className="mt-1.5 text-xs italic text-amber-600/80 dark:text-amber-400/70">
              {block.unschedulable_reason}
            </p>
          )}
          {block.constraints && block.constraints.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {block.constraints.map((constraint) => (
                <span
                  key={constraint}
                  className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-500 dark:bg-zinc-800/50 dark:text-zinc-400"
                >
                  {constraint}
                </span>
              ))}
            </div>
          )}
          {showPriceEstimates && block.price_estimate && (
            <span className="mt-2 inline-block text-xs font-medium text-zinc-500 dark:text-zinc-400">
              ~${block.price_estimate.toLocaleString()}
            </span>
          )}
          {block.buffer_reason && (
            <div className="mt-2 inline-block rounded bg-zinc-500/10 px-2 py-1 text-xs font-medium text-zinc-600 dark:bg-zinc-500/15 dark:text-zinc-400">
              {block.buffer_reason}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
