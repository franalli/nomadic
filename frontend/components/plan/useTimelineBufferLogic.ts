'use client';

/**
 * useTimelineBufferLogic
 *
 * Encapsulates the buffer/exclusion constraint logic for free day cards.
 * Determines which activity categories are excluded based on
 * same-day buffer blocks (BUFFER_EXCLUSIONS). Adjacent-day cross-domain
 * safety is enforced by the backend constraint guard during generation.
 *
 * Extracted from TimelineThread to reduce file size.
 */

import { useMemo } from 'react';

import { BUFFER_EXCLUSIONS } from '@/lib/categoryNormalization';
import type { DayBlock } from '@/types/plan-envelope';

const CATEGORY_ICONS: Record<string, string> = {
  diving: '\u{1F93F}', hiking: '\u{1F97E}', skiing: '\u26F7\uFE0F', cycling: '\u{1F6B4}',
  sailing: '\u26F5', surfing: '\u{1F3C4}', cooking: '\u{1F373}', yoga: '\u{1F9D8}',
  temples: '\u26E9\uFE0F', nightlife: '\u{1F389}', beach: '\u{1F3D6}\uFE0F', shopping: '\u{1F6CD}\uFE0F',
  photography: '\u{1F4F8}',
};

export interface BufferLogicResult {
  /** Categories available to show as chips (null if chips should be hidden) */
  chipsToShow: Array<{ value: string; label: string; icon: string }> | undefined;
  /** True when all user-selected activity types are blocked by constraints */
  isConstraintBuffer: boolean;
}

/**
 * Compute excluded categories and available chips for a free day card.
 */
export function computeBufferExclusions(
  bufferBlocks: DayBlock[],
  categories: string[] | undefined,
): BufferLogicResult {
  // Build excluded category set from same-day buffer blocks only.
  // Adjacent-day cross-domain safety is enforced by the backend constraint
  // guard during generation — the frontend chips show all user-selected
  // categories so the user retains full agency over free day planning.
  const excludedByConstraint = new Set<string>();
  for (const buf of bufferBlocks) {
    const st = (buf.specialist_type || '').toLowerCase();
    if (st && BUFFER_EXCLUSIONS[st]) {
      BUFFER_EXCLUSIONS[st].forEach(cat => excludedByConstraint.add(cat));
    }
  }
  const filteredCategories = categories
    ? categories.filter(c => !excludedByConstraint.has(c.toLowerCase()))
    : undefined;
  // A day is a "constraint buffer" when it has buffer blocks AND
  // every user-selected activity type is excluded by constraints.
  // On such days: suppress chips + auto-generate CTA; show Browse instead.
  const isConstraintBuffer = bufferBlocks.length > 0
    && !!categories
    && categories.length > 0
    && filteredCategories?.length === 0;
  const chipsToShow = (categories && categories.length > 1 && !isConstraintBuffer)
    ? filteredCategories?.map(c => ({
        value: c,
        label: c.charAt(0).toUpperCase() + c.slice(1),
        icon: CATEGORY_ICONS[c.toLowerCase()] ?? '\u{1F3AF}',
      }))
    : undefined;

  return { chipsToShow, isConstraintBuffer };
}

/**
 * React hook wrapping computeBufferExclusions with memoization.
 */
export function useTimelineBufferLogic(
  bufferBlocks: DayBlock[],
  categories: string[] | undefined,
): BufferLogicResult {
  return useMemo(
    () => computeBufferExclusions(bufferBlocks, categories),
    [bufferBlocks, categories],
  );
}
