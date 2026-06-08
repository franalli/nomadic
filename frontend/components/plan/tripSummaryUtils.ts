/**
 * tripSummaryUtils
 *
 * Pure domain logic extracted from TripSummaryPills:
 * category resolution, day counting, block matching.
 * No React dependencies — fully testable.
 */

import {
  isBadgedActivityBlock,
  resolveActivityCategory,
} from '@/components/plan/timeline/blocks/ActivityCardMeta.helpers';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

// Single resolver: delegate to resolveActivityCategory -- the SAME function the
// day-card badges use -- guarded by the shared isBadgedActivityBlock so buffers
// and arrival/departure/check-in blocks (which show no badge) resolve to null and
// are never mirrored as a scheduled category. One chain + one guard, no drift.
export function resolveBlockCategory(block: DayBlock): string | null {
  if (!isBadgedActivityBlock(block)) return null;
  return resolveActivityCategory(block)?.key ?? null;
}

function blockTextForMatching(block: DayBlock): string {
  return `${String(block.activity_type ?? '')} ${String(block.summary ?? '')}`.toLowerCase();
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function blockMatchesCategory(block: DayBlock, category: string): boolean {
  const resolved = resolveBlockCategory(block);
  if (resolved === category) return true;

  const haystack = blockTextForMatching(block);
  const token = category.replace(/_/g, ' ').trim().toLowerCase();
  if (!token) return false;
  const re = new RegExp(`\\b${escapeRegex(token)}\\b`, 'i');
  return re.test(haystack);
}

export function deriveScheduledDayCounts(
  dayCards: DayCard[] | undefined,
  selectedCategories: string[] = []
): Map<string, number> {
  const categoryToDays = new Map<string, Set<number>>();
  if (!dayCards || dayCards.length === 0) return new Map();
  const selected = Array.from(new Set(selectedCategories));

  if (selected.length > 0) {
    selected.forEach((cat) => categoryToDays.set(cat, new Set<number>()));

    dayCards.forEach((card) => {
      card.blocks?.forEach((block) => {
        selected.forEach((selectedCategory) => {
          if (blockMatchesCategory(block, selectedCategory)) {
            categoryToDays.get(selectedCategory)?.add(card.day_number);
          }
        });
      });
    });
  } else {
    dayCards.forEach((card) => {
      card.blocks?.forEach((block) => {
        const category = resolveBlockCategory(block);
        if (category) {
          const existing = categoryToDays.get(category) ?? new Set<number>();
          existing.add(card.day_number);
          categoryToDays.set(category, existing);
        }
      });
    });
  }

  const counts = new Map<string, number>();
  categoryToDays.forEach((days, category) => counts.set(category, days.size));
  return counts;
}
