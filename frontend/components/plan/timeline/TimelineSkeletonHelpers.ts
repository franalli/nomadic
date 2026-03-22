import type { SpecialistPreviewActivity } from '@/lib/api-streaming';
import type { StrategySection } from '@/types/plan-envelope';

export interface PreviewItem {
  title: string;
  description?: string;
  specialistLabel: string;
  durationHours?: number | null;
}

export function formatSpecialistLabel(value: string | undefined): string {
  if (!value) return 'Specialist';
  return value.replace(/_/g, ' ');
}

export function collectPreviewItems(
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

export function collectPreviewItemsFromActivities(
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

// Shimmer base classes
export const shimmerClasses = 'bg-zinc-200 dark:bg-zinc-700 animate-pulse';
