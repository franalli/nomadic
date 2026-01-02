/**
 * Small badge component for showing differences between trips.
 *
 * Variants:
 * - positive (green): Better value (e.g., saves money, more activities)
 * - negative (red): Worse value (e.g., more expensive)
 * - neutral (blue): Informational, no value judgment
 */

import { cn } from '@/lib/utils';

import type { ValueDiff } from './hooks/useComparisonMode';

type ComparisonDiffBadgeProps = {
  diff: ValueDiff;
  className?: string;
  size?: 'sm' | 'md';
};

const variantStyles = {
  positive: 'bg-green-100 text-green-700',
  negative: 'bg-red-100 text-red-700',
  neutral: 'bg-blue-100 text-blue-700',
} as const;

const sizeStyles = {
  sm: 'px-1.5 py-0.5 text-xs',
  md: 'px-2 py-1 text-sm',
} as const;

export function ComparisonDiffBadge({
  diff,
  className,
  size = 'sm',
}: ComparisonDiffBadgeProps) {
  // Don't show badge if values are the same
  if (diff.direction === 'neutral' && diff.value === 0) {
    return null;
  }

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full font-medium whitespace-nowrap',
        variantStyles[diff.direction],
        sizeStyles[size],
        className
      )}
    >
      {diff.formatted}
    </span>
  );
}

/**
 * Helper component to conditionally render a diff badge.
 */
type OptionalDiffBadgeProps = {
  diff: ValueDiff | null | undefined;
  className?: string;
  size?: 'sm' | 'md';
};

export function OptionalDiffBadge({ diff, ...props }: OptionalDiffBadgeProps) {
  if (!diff) return null;
  return <ComparisonDiffBadge diff={diff} {...props} />;
}
