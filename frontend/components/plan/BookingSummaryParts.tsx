import { ExternalLink } from 'lucide-react';

import { formatPrice, formatTilePrice } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { DayBlock,PlanViewState  } from '@/types/plan-envelope';

export const VISIBLE_STATES: Set<PlanViewState> = new Set([
  'S3_ITINERARY_READY',
  'S3_EDITING',
  'P3_FINALIZED',
  'P3_EDITING',
]);

export const PRICE_LEVEL_LABELS: Record<number, string> = {
  0: 'Free',
  1: '$',
  2: '$$',
  3: '$$$',
  4: '$$$$',
};

export interface VenueLinkRowProps {
  href: string;
  price?: string | null;
  title: string;
}

export interface VenueLinkRowData extends VenueLinkRowProps {
  dedupeKey: string;
  id: string;
}

export function formatActivityPrice(block: DayBlock): string | null {
  if (block.booked_tile) {
    const bookedTilePrice = formatTilePrice(block.booked_tile);
    if (bookedTilePrice) return bookedTilePrice;
  }

  if (block.price_estimate != null && block.price_estimate > 0) {
    return `~${formatPrice(block.price_estimate)}`;
  }

  if (
    block.price_level != null &&
    Object.prototype.hasOwnProperty.call(PRICE_LEVEL_LABELS, block.price_level)
  ) {
    return PRICE_LEVEL_LABELS[block.price_level];
  }

  return null;
}

export function VenueLinkRow({ href, price, title }: VenueLinkRowProps) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        'group flex items-center justify-between gap-3 px-4 py-2.5',
        'border-b border-zinc-200/70 transition-colors last:border-b-0',
        'hover:bg-zinc-50/80 dark:border-white/5 dark:hover:bg-white/[0.03]',
      )}
    >
      <span className="min-w-0 flex-1 truncate text-sm text-emerald-600 transition-colors group-hover:text-emerald-500 dark:text-emerald-400 dark:group-hover:text-emerald-300">
        {title}
      </span>
      <span className="flex shrink-0 items-center gap-1 whitespace-nowrap text-xs text-zinc-500 dark:text-zinc-400">
        {price ? <span>{price}</span> : null}
        <ExternalLink className="h-3 w-3 shrink-0" />
      </span>
    </a>
  );
}

export function dedupeVenueRows(rows: VenueLinkRowData[]): VenueLinkRowData[] {
  const seen = new Set<string>();

  return rows.filter((row) => {
    if (seen.has(row.dedupeKey)) return false;
    seen.add(row.dedupeKey);
    return true;
  });
}

interface VenueLinkSectionProps {
  label: string;
  rows: VenueLinkRowData[];
  showBorder: boolean;
}

export function VenueLinkSection({ label, rows, showBorder }: VenueLinkSectionProps) {
  if (rows.length === 0) return null;
  return (
    <div className={cn(showBorder && 'border-t border-zinc-200/70 dark:border-white/5')}>
      <div className="px-4 pt-3 pb-1">
        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">
          {label}
        </span>
      </div>
      <div>
        {rows.map((row) => (
          <VenueLinkRow
            key={row.id}
            href={row.href}
            price={row.price}
            title={row.title}
          />
        ))}
      </div>
    </div>
  );
}
