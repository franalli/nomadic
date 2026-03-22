/**
 * tripSummaryUtils
 *
 * Pure domain logic extracted from TripSummaryPills:
 * category resolution, day counting, block matching.
 * No React dependencies — fully testable.
 */

import { canonicalCategoryKey, TIER1_CONSTRAINT_HINTS, toCategoryKey } from '@/lib/categoryNormalization';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

const NON_ACTIVITY_TYPES = new Set([
  'arrival',
  'departure',
  'check-in',
  'check-out',
  'check_in',
  'check_out',
  'free_day',
  'rest_day',
  'buffer',
  'decompression_buffer',
]);

export function resolveBlockCategory(block: DayBlock): string | null {
  if (block.is_buffer) return null;
  const activityType = toCategoryKey(block.activity_type);
  if (activityType && NON_ACTIVITY_TYPES.has(activityType)) return null;

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
    : undefined;

  return (
    canonicalCategoryKey(block.map_type) ??
    canonicalCategoryKey(block.specialist_type) ??
    canonicalCategoryKey(bookedTile?.map_type) ??
    canonicalCategoryKey(meta?.map_type) ??
    canonicalCategoryKey((bookedTile as Record<string, unknown> | undefined)?.browse_category) ??
    canonicalCategoryKey(bookedTile?.category) ??
    canonicalCategoryKey(meta?.category)
  );
}

export function inferConstraintCategories(block: DayBlock): string[] {
  const categories = new Set<string>();
  const specialist = canonicalCategoryKey(block.specialist_type);
  if (specialist && specialist in TIER1_CONSTRAINT_HINTS) {
    categories.add(specialist);
  }

  const textParts: string[] = [];
  if (typeof block.buffer_reason === 'string') textParts.push(block.buffer_reason);
  if (Array.isArray(block.constraints)) {
    textParts.push(...block.constraints.filter((c): c is string => typeof c === 'string'));
  }
  if (Array.isArray(block.active_constraints)) {
    block.active_constraints.forEach((c) => {
      if (typeof c.id === 'string') textParts.push(c.id);
      if (typeof c.title === 'string') textParts.push(c.title);
      if (typeof c.description === 'string') textParts.push(c.description);
    });
  }
  const text = textParts.join(' ');
  if (!text) return Array.from(categories);

  Object.entries(TIER1_CONSTRAINT_HINTS).forEach(([category, patterns]) => {
    if (patterns.some((pattern) => pattern.test(text))) {
      categories.add(category);
    }
  });
  return Array.from(categories);
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
        const inferredConstraints = new Set(inferConstraintCategories(block));
        selected.forEach((selectedCategory) => {
          if (
            inferredConstraints.has(selectedCategory) ||
            blockMatchesCategory(block, selectedCategory)
          ) {
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

        inferConstraintCategories(block).forEach((constraintCategory) => {
          const existing = categoryToDays.get(constraintCategory) ?? new Set<number>();
          existing.add(card.day_number);
          categoryToDays.set(constraintCategory, existing);
        });
      });
    });
  }

  const counts = new Map<string, number>();
  categoryToDays.forEach((days, category) => counts.set(category, days.size));
  return counts;
}
