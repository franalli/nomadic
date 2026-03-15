'use client';

import { ExternalLink } from 'lucide-react';
import type { ReactNode } from 'react';
import { useMemo } from 'react';

import { getEffectiveTileDeeplinkUrl } from '@/components/tiles/tileHelpers';
import { DS } from '@/lib/design-system';
import { formatPrice, formatTilePrice } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { DayBlock, DayCard, PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

const VISIBLE_STATES: Set<PlanViewState> = new Set([
  'S3_ITINERARY_READY',
  'S3_EDITING',
  'P3_FINALIZED',
  'P3_EDITING',
]);

const PRICE_LEVEL_LABELS: Record<number, string> = {
  0: 'Free',
  1: '$',
  2: '$$',
  3: '$$$',
  4: '$$$$',
};

interface VenueLinkRowProps {
  href: string;
  price?: string | null;
  title: string;
}

interface VenueLinkRowData extends VenueLinkRowProps {
  dedupeKey: string;
  id: string;
}

function formatActivityPrice(block: DayBlock): string | null {
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

function VenueLinkRow({ href, price, title }: VenueLinkRowProps) {
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

function dedupeVenueRows(rows: VenueLinkRowData[]): VenueLinkRowData[] {
  const seen = new Set<string>();

  return rows.filter((row) => {
    if (seen.has(row.dedupeKey)) return false;
    seen.add(row.dedupeKey);
    return true;
  });
}

interface BookingSummaryProps {
  tiles: Record<string, Tile>;
  dayCards: DayCard[];
  state: PlanViewState;
  headerActions?: ReactNode;
}

export function BookingSummary({
  tiles,
  dayCards,
  state,
  headerActions,
}: BookingSummaryProps) {
  const tripInputs = useDocumentTripInputs();
  const hotelLinks = useMemo(
    () =>
      Object.values(tiles).filter(
        (t) =>
          (t.type === 'hotel' || t.type === 'accommodation' || t.type === 'stay') &&
          t.deeplink_url &&
          t.deeplink_url !== '#' &&
          t.deeplink_url !== ''
      ),
    [tiles]
  );

  const activityLinks = useMemo(
    () =>
      dayCards
        .flatMap((dc) => dc.blocks)
        .filter((b) => b.deeplink && b.deeplink !== '' && !b.is_buffer && !b.is_skeleton),
    [dayCards]
  );

  const hotelRows = useMemo(
    () =>
      dedupeVenueRows(
        hotelLinks.map((tile) => {
          const deeplinkUrl = getEffectiveTileDeeplinkUrl(tile, tripInputs);

          return {
            dedupeKey: tile.partner_product_id || deeplinkUrl || tile.id,
            href: deeplinkUrl,
            id: tile.id,
            price: formatTilePrice(tile) || null,
            title: tile.title,
          };
        })
      ),
    [hotelLinks, tripInputs]
  );

  const flightRows = useMemo(
    () =>
      dedupeVenueRows(
        dayCards
          .flatMap((dc) => dc.blocks)
          .filter(
            (block) =>
              block.booking_category === 'flight' &&
              block.booked_tile?.deeplink_url &&
              block.booked_tile.deeplink_url !== '#'
          )
          .map((block, index) => ({
            dedupeKey:
              block.booked_tile?.partner_product_id
              || block.booked_tile?.deeplink_url
              || block.booked_tile?.id
              || block.id
              || `${block.period}-${block.summary}-${block.activity_type}-${index}`,
            href: block.booked_tile?.deeplink_url as string,
            id:
              block.booked_tile?.id ??
              block.id ??
              `${block.period}-${block.summary}-${block.activity_type}-${index}`,
            price: block.booked_tile ? formatTilePrice(block.booked_tile) || null : null,
            title: block.booked_tile?.title || block.summary || 'Flight',
          }))
      ),
    [dayCards]
  );

  const activityRows = useMemo(
    () =>
      dedupeVenueRows(
        activityLinks.map((block, index) => ({
          dedupeKey:
            block.booked_tile?.partner_product_id
            || block.deeplink
            || block.id
            || `${block.period}-${block.summary}-${block.activity_type}-${index}`,
          href: block.deeplink as string,
          id: block.id ?? `${block.period}-${block.summary}-${block.activity_type}-${index}`,
          price: formatActivityPrice(block),
          title: block.summary || block.booked_tile?.title || block.activity_type || 'Activity',
        }))
      ),
    [activityLinks]
  );

  if (!VISIBLE_STATES.has(state)) return null;
  if (hotelRows.length === 0 && flightRows.length === 0 && activityRows.length === 0) return null;

  return (
    <div className={cn(DS.materials.glass, 'mt-6 overflow-hidden')}>
      <div className="flex items-center justify-between gap-3 border-b border-zinc-200/70 px-4 py-3 dark:border-white/5">
        <h3 className={DS.text.label}>Booking Links</h3>
        {headerActions ? (
          <div
            className={cn(
              'flex items-center gap-3',
              '[&_button]:rounded-none [&_button]:px-0 [&_button]:py-0 [&_button]:font-semibold',
              '[&_button]:normal-case [&_button]:tracking-normal [&_button]:shadow-none',
              '[&_button]:text-xs [&_button]:text-zinc-500 [&_button:hover]:bg-transparent',
              '[&_button:hover]:text-zinc-900 dark:[&_button]:text-zinc-400 dark:[&_button:hover]:text-white',
              '[&_svg]:hidden'
            )}
          >
            {headerActions}
          </div>
        ) : null}
      </div>

      {hotelRows.length > 0 && (
        <div>
          <div className="px-4 pt-3 pb-1">
            <span className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">
              Stays
            </span>
          </div>
          <div>
            {hotelRows.map((row) => (
              <VenueLinkRow
                key={row.id}
                href={row.href}
                price={row.price}
                title={row.title}
              />
            ))}
          </div>
        </div>
      )}

      {flightRows.length > 0 && (
        <div className={cn(hotelRows.length > 0 && 'border-t border-zinc-200/70 dark:border-white/5')}>
          <div className="px-4 pt-3 pb-1">
            <span className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">
              Flights
            </span>
          </div>
          <div>
            {flightRows.map((row) => (
              <VenueLinkRow
                key={row.id}
                href={row.href}
                price={row.price}
                title={row.title}
              />
            ))}
          </div>
        </div>
      )}

      {activityRows.length > 0 && (
        <div className={cn((hotelRows.length > 0 || flightRows.length > 0) && 'border-t border-zinc-200/70 dark:border-white/5')}>
          <div className="px-4 pt-3 pb-1">
            <span className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">
              Activities
            </span>
          </div>
          <div>
            {activityRows.map((row) => (
              <VenueLinkRow
                key={row.id}
                href={row.href}
                price={row.price}
                title={row.title}
              />
            ))}
          </div>
        </div>
      )}

      <p
        className={cn(
          DS.textSize.micro,
          'border-t border-zinc-200/70 px-4 py-3 text-zinc-500 dark:border-white/5 dark:text-zinc-400'
        )}
      >
        Links open partner booking pages, Google Travel Hotels, and Google Maps
      </p>
    </div>
  );
}
