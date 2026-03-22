/**
 * Helper functions for useChatSend.
 *
 * Stateless utility functions extracted from useChatSend.ts.
 * Minimal React coupling — only `waitForPendingMutationsToSettle` accesses the document store.
 */

import { parseISODateLocal } from '@/lib/date-utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';

export function buildSendRequestId(now: number): string {
  return `req_${now}_${Math.random().toString(36).slice(2, 8)}`;
}

export function buildMessageSignature(
  message: string,
  selectedBranchId: string | null,
  tripInputs: DocumentTripInputs | null | undefined,
  suggestionClicked?: string
): string {
  return JSON.stringify({
    m: message.trim().toLowerCase(),
    s: suggestionClicked?.trim().toLowerCase() ?? null,
    b: selectedBranchId,
    d: tripInputs?.destination ?? null,
    sd: tripInputs?.start_date ?? null,
    ed: tripInputs?.end_date ?? null,
    a: tripInputs?.adults ?? null,
    c: tripInputs?.children ?? null,
    o: tripInputs?.origin ?? null,
    bg: tripInputs?.budget ?? null,
  });
}

const EXTEND_BY_DAYS_PATTERN = /^(?:please\s+)?extend(?:\s+by)?\s+(\d+)\s+days?$/i;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

function formatISODateLocal(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseDateExtensionDays(message: string): number | null {
  const match = message.trim().match(EXTEND_BY_DAYS_PATTERN);
  if (!match) return null;
  const parsed = Number.parseInt(match[1] ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function computeInclusiveTripDays(startDate: Date, endDate: Date): number {
  const startUtc = Date.UTC(startDate.getFullYear(), startDate.getMonth(), startDate.getDate());
  const endUtc = Date.UTC(endDate.getFullYear(), endDate.getMonth(), endDate.getDate());
  return Math.floor((endUtc - startUtc) / MS_PER_DAY) + 1;
}

export function buildOptimisticExtensionPreview(
  message: string,
  tripInputs: DocumentTripInputs | null | undefined,
  dayCards: DayCard[] | undefined
): { tripInputs: DocumentTripInputs; dayCards: DayCard[] } | null {
  const extensionDays = parseDateExtensionDays(message);
  if (!extensionDays || !tripInputs?.start_date || !tripInputs.end_date || !dayCards?.length) {
    return null;
  }

  const startDate = parseISODateLocal(tripInputs.start_date);
  const currentEndDate = parseISODateLocal(tripInputs.end_date);
  if (!startDate || !currentEndDate) {
    return null;
  }

  const nextEndDate = new Date(currentEndDate.getTime());
  nextEndDate.setDate(nextEndDate.getDate() + extensionDays);

  const totalDays = computeInclusiveTripDays(startDate, nextEndDate);
  if (totalDays <= dayCards.length) {
    return null;
  }

  const optimisticDayCards = structuredClone(dayCards) as DayCard[];
  for (let dayNumber = optimisticDayCards.length + 1; dayNumber <= totalDays; dayNumber += 1) {
    const dayDate = new Date(startDate.getTime());
    dayDate.setDate(startDate.getDate() + dayNumber - 1);
    optimisticDayCards.push({
      day_number: dayNumber,
      date: formatISODateLocal(dayDate),
      label: 'Planning in progress',
      blocks: [
        {
          period: 'morning',
          activity_type: 'planning_placeholder',
          summary: `Planning Day ${dayNumber}...`,
          is_skeleton: true,
        },
      ],
    });
  }

  return {
    tripInputs: {
      ...tripInputs,
      end_date: formatISODateLocal(nextEndDate),
      trip_duration: totalDays,
    },
    dayCards: optimisticDayCards,
  };
}

export function didOptimisticExtensionRegress(
  currentTripInputs: DocumentTripInputs | null | undefined,
  previousTripInputs: DocumentTripInputs | null | undefined,
  optimisticExtension: { tripInputs: DocumentTripInputs; dayCards: DayCard[] } | null
): boolean {
  if (!currentTripInputs || !previousTripInputs || !optimisticExtension) {
    return false;
  }

  const previousEndDate = previousTripInputs.end_date;
  const optimisticEndDate = optimisticExtension.tripInputs.end_date;
  const currentEndDate = currentTripInputs.end_date;
  if (!previousEndDate || !optimisticEndDate || !currentEndDate) {
    return false;
  }

  const previousEnd = parseISODateLocal(previousEndDate);
  const optimisticEnd = parseISODateLocal(optimisticEndDate);
  const currentEnd = parseISODateLocal(currentEndDate);
  if (!previousEnd || !optimisticEnd || !currentEnd) {
    return false;
  }

  if (optimisticEnd.getTime() <= previousEnd.getTime()) {
    return false;
  }

  return currentEnd.getTime() <= previousEnd.getTime();
}

export function shouldStartPlanGeneration({
  isGenerateTrigger,
  hasBranches,
  message,
  readyToGenerate,
  tripInputs,
}: {
  isGenerateTrigger: boolean;
  hasBranches?: boolean;
  message: string;
  readyToGenerate?: boolean;
  tripInputs: DocumentTripInputs | null | undefined;
}): boolean {
  if (isGenerateTrigger) return true;
  if (readyToGenerate === true) return true;
  if (hasBranches) return false;

  const normalized = message.trim().toLowerCase();
  const hasDateCue =
    /\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*-\s*\d{1,2}(?:st|nd|rd|th)?)?|this weekend|next weekend|long weekend)\b/i.test(
      normalized
    );
  if (!hasDateCue) return false;

  if (tripInputs?.destination) return true;
  if (/\bfrom\b/.test(normalized)) return true;
  if (
    /\b(?:trip|travel|vacation|holiday|getaway|itinerary|plan|hotel|stay|flight)\b/.test(
      normalized
    )
  ) {
    return true;
  }

  return normalized.split(/\s+/).filter(Boolean).length >= 4;
}

export function waitForPendingMutationsToSettle(timeoutMs = 5_000): Promise<boolean> {
  if (!useDocumentStore.getState().hasPendingMutations()) {
    return Promise.resolve(true);
  }

  return new Promise<boolean>((resolve) => {
    let settled = false;
    let unsubscribe: (() => void) | null = null;

    const settle = (ready: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      unsubscribe?.();
      resolve(ready);
    };

    const timeout = setTimeout(() => settle(false), timeoutMs);
    unsubscribe = useDocumentStore.subscribe((state, prev) => {
      if (state._pendingMutations !== prev._pendingMutations && !state.hasPendingMutations()) {
        settle(true);
      }
    });

    if (!useDocumentStore.getState().hasPendingMutations()) {
      settle(true);
    }
  });
}
