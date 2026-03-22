import { formatPrice } from '@/lib/format-utils';

export function formatPriceOrDash(price: number | undefined): string {
  if (!price) return '\u2014';
  return formatPrice(price);
}

export function getPriceDiff(
  current: number | undefined,
  alternative: number | undefined
): { value: number; label: string; type: 'cheaper' | 'more' | 'same' } | null {
  if (!current || !alternative) return null;
  const diff = alternative - current;
  if (Math.abs(diff) < 1) return { value: 0, label: 'Same price', type: 'same' };
  if (diff < 0) return { value: Math.abs(diff), label: `-$${Math.abs(diff)}`, type: 'cheaper' };
  return { value: diff, label: `+$${diff}`, type: 'more' };
}

export function getRatingDiff(
  current: number | undefined,
  alternative: number | undefined
): { value: number; label: string; type: 'better' | 'worse' | 'same' } | null {
  if (!current || !alternative) return null;
  const diff = alternative - current;
  if (Math.abs(diff) < 0.1) return { value: 0, label: 'Same rating', type: 'same' };
  if (diff > 0)
    return { value: diff, label: `+${diff.toFixed(1)}`, type: 'better' };
  return { value: Math.abs(diff), label: `${diff.toFixed(1)}`, type: 'worse' };
}
