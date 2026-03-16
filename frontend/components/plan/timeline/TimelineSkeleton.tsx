'use client';

import { useMemo } from 'react';

import type { SpecialistPreviewActivity } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { StrategySection } from '@/types/plan-envelope';

interface PreviewItem {
  title: string;
  description?: string;
  specialistLabel: string;
  durationHours?: number | null;
}

function formatSpecialistLabel(value: string | undefined): string {
  if (!value) return 'Specialist';
  return value.replace(/_/g, ' ');
}

function collectPreviewItems(
  strategySections: StrategySection[] | undefined
): PreviewItem[] {
  if (!strategySections) return [];

  const previewItems: PreviewItem[] = [];

  for (const section of strategySections) {
    const specialistType = section.specialist_type;
    if (
      !specialistType ||
      specialistType === 'general' ||
      specialistType === 'local_expert' ||
      section.feasibility_status === 'infeasible'
    ) {
      continue;
    }

    for (const content of section.content_added ?? []) {
      const title = content.title?.trim();
      if (!title) continue;

      previewItems.push({
        title,
        description: content.description?.trim() || undefined,
        specialistLabel: formatSpecialistLabel(specialistType),
      });

      if (previewItems.length >= 3) {
        return previewItems;
      }
    }
  }

  return previewItems;
}

function collectPreviewItemsFromActivities(
  activities: SpecialistPreviewActivity[] | null
): PreviewItem[] {
  if (!activities?.length) return [];

  return activities
    .filter((activity) => Boolean(activity.title?.trim()))
    .slice(0, 3)
    .map((activity) => ({
      title: activity.title.trim(),
      description: activity.description?.trim() || undefined,
      specialistLabel: formatSpecialistLabel(activity.specialist_type),
      durationHours: activity.duration_hours ?? null,
    }));
}

/**
 * TimelineSkeleton
 *
 * Premium loading state shown while itinerary is being generated.
 * Uses shimmer animation for a more polished feel.
 */
export function TimelineSkeleton() {
  const specialistPreview = useDocumentStore((s) => s._specialistPreview);
  const strategySections = useDocumentStore((s) => s.document?.strategy_sections);
  const previewItems = useMemo(
    () => {
      const activityPreviewItems = collectPreviewItemsFromActivities(specialistPreview);
      return activityPreviewItems.length > 0
        ? activityPreviewItems
        : collectPreviewItems(strategySections);
    },
    [specialistPreview, strategySections]
  );

  return (
    <div className="pl-4 pr-2 py-6 space-y-10 relative">
      {/* Thread Line - dotted while loading */}
      <div className="absolute left-[31px] top-6 bottom-6 w-0.5 border-l-2 border-dotted border-zinc-300 dark:border-white/10" />

      {[1, 2, 3].map((i) => {
        const preview = previewItems[i - 1];

        return (
          <div
            key={i}
            className={cn(
              'relative z-10 pl-10',
              i === 1 && '[animation-delay:150ms]',
              i === 2 && '[animation-delay:300ms]',
              i === 3 && '[animation-delay:450ms]',
            )}
          >
            {/* Day Header Bead - pulsing ring */}
            <div className="absolute -left-[1px] top-1">
              <div className="w-9 h-9 rounded-full bg-zinc-200 dark:bg-zinc-800 animate-pulse" />
              <div className="absolute inset-0 w-9 h-9 rounded-full ring-2 ring-emerald-500/20 animate-ping [animation-duration:2s]" />
            </div>

            {/* Day Label with shimmer */}
            <div className="mb-3 space-y-2">
              {preview ? (
                <>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500 dark:text-zinc-400">
                    {preview.specialistLabel}
                  </div>
                  <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100 line-clamp-1">
                    {preview.title}
                  </div>
                </>
              ) : (
                <>
                  <div className={cn('h-5 w-24 rounded', shimmerClasses)} />
                  <div className={cn('h-3 w-36 rounded [animation-delay:100ms]', shimmerClasses)} />
                </>
              )}
            </div>

            {/* Content Card with shimmer stripes */}
            <div
              className={cn(
                'relative h-32 w-full rounded-xl border overflow-hidden',
                preview
                  ? 'border-emerald-200/70 bg-white/80 shadow-sm dark:border-emerald-500/20 dark:bg-zinc-900/50'
                  : 'border-dashed border-zinc-300 bg-zinc-100/50 dark:border-white/10 dark:bg-zinc-800/30'
              )}
            >
              {/* Shimmer overlay */}
              {!preview && (
                <div className="absolute inset-0 -translate-x-full animate-[shimmer_2s_infinite] bg-gradient-to-r from-transparent via-white/20 dark:via-white/5 to-transparent" />
              )}

              {/* Skeleton content */}
              <div className="p-4 space-y-2">
                {preview ? (
                  <>
                    <div className="text-sm leading-5 text-zinc-600 dark:text-zinc-300 line-clamp-3">
                      {preview.description ?? 'Specialist guidance is ready while availability finishes loading.'}
                    </div>
                    <div className="pt-1 text-xs capitalize text-zinc-500 dark:text-zinc-400">
                      {preview.durationHours
                        ? `${preview.durationHours}h · ${preview.specialistLabel}`
                        : preview.specialistLabel}
                    </div>
                  </>
                ) : (
                  <>
                    <div className={cn('h-4 w-3/4 rounded', shimmerClasses)} />
                    <div className={cn('h-3 w-1/2 rounded [animation-delay:150ms]', shimmerClasses)} />
                    <div className={cn('h-3 w-2/3 rounded [animation-delay:300ms]', shimmerClasses)} />
                  </>
                )}
              </div>

              {/* Building indicator */}
              <div className={`absolute bottom-3 right-3 flex items-center gap-1.5 ${DS.textSize.micro} text-zinc-400`}>
                <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />
                {preview ? 'Specialist preview' : `Building day ${i}`}
              </div>
            </div>
          </div>
        );
      })}

      {/* Loading indicator at bottom */}
      <div className="text-center pt-4 pb-2">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-zinc-100 dark:bg-zinc-800">
          <div className="flex gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-bounce [animation-delay:300ms]" />
          </div>
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            {previewItems.length > 0
              ? 'Loading live availability around specialist picks'
              : 'Creating your personalized itinerary'}
          </span>
        </div>
      </div>
    </div>
  );
}

// Shimmer base classes
const shimmerClasses = 'bg-zinc-200 dark:bg-zinc-700 animate-pulse';

export default TimelineSkeleton;
