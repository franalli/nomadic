import type { PlanStatus } from '@/types/plan-status';

/**
 * Derive the effective phase from plan status using strict precedence.
 *
 * Priority order:
 * 1. Any specialist error → 'error'
 * 2. Required fields missing → 'needs_input'
 * 3. Any specialist queued or running → 'updating'
 * 4. Otherwise → 'ready'
 */
export function deriveEffectivePhase(status: PlanStatus): PlanStatus['phase'] {
  const { missing, activeSpecialists } = status;

  // 1. Any specialist error → error
  if (activeSpecialists.some((s) => s.state === 'error')) {
    return 'error';
  }

  // 2. Required fields missing → needs_input
  if (missing.length > 0) {
    return 'needs_input';
  }

  // 3. Any specialist queued or running → updating
  if (activeSpecialists.some((s) => s.state === 'queued' || s.state === 'running')) {
    return 'updating';
  }

  // 4. Otherwise → ready
  return 'ready';
}

/**
 * Field key to display label mapping
 */
const FIELD_LABELS: Record<string, string> = {
  origin: 'origin',
  destinations: 'destination',
  start_date: 'dates',
  end_date: 'dates',
  dates: 'dates',
};

/**
 * Format missing fields for display.
 * Shows first 2 fields, then "+N" if more.
 *
 * @example formatMissing(['origin', 'start_date']) → 'origin, dates'
 * @example formatMissing(['origin', 'start_date', 'budget']) → 'origin, dates +1'
 */
export function formatMissing(missing: string[]): string {
  // Deduplicate and map to labels
  const labels = new Set<string>();
  for (const field of missing) {
    labels.add(FIELD_LABELS[field] || field);
  }
  const unique = Array.from(labels);

  if (unique.length === 0) return '';
  if (unique.length <= 2) return unique.join(', ');
  return `${unique.slice(0, 2).join(', ')} +${unique.length - 2}`;
}
