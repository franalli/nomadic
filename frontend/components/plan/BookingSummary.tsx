'use client';

import type { ReactNode } from 'react';
import { useMemo } from 'react';

import { getEffectiveTileDeeplinkUrl } from '@/components/tiles/tileHelpers';
import { DS } from '@/lib/design-system';
import { formatTilePrice } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { DayCard, PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import {
  dedupeVenueRows,
  formatActivityPrice,
  VenueLinkSection,
  VISIBLE_STATES,
} from './BookingSummaryParts';

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

      <VenueLinkSection label="Stays" rows={hotelRows} showBorder={false} />
      <VenueLinkSection label="Flights" rows={flightRows} showBorder={hotelRows.length > 0} />
      <VenueLinkSection
        label="Activities"
        rows={activityRows}
        showBorder={hotelRows.length > 0 || flightRows.length > 0}
      />

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
