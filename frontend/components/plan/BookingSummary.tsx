'use client';

import { ExternalLink } from 'lucide-react';
import { useMemo } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { DayCard, PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

const VISIBLE_STATES: Set<PlanViewState> = new Set([
  'S3_ITINERARY_READY',
  'S3_EDITING',
  'P3_FINALIZED',
  'P3_EDITING',
]);

interface BookingSummaryProps {
  tiles: Record<string, Tile>;
  dayCards: DayCard[];
  state: PlanViewState;
}

export function BookingSummary({ tiles, dayCards, state }: BookingSummaryProps) {
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

  if (!VISIBLE_STATES.has(state)) return null;
  if (hotelLinks.length === 0 && activityLinks.length === 0) return null;

  return (
    <div className={cn(DS.materials.glass, 'p-5 mt-6')}>
      <h3 className={cn(DS.text.label, 'mb-4')}>Venue Links</h3>

      {hotelLinks.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-2">Stays</p>
          <div className="flex flex-col gap-1.5">
            {hotelLinks.map((tile) => (
              <a
                key={tile.id}
                href={tile.deeplink_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm text-emerald-500 hover:text-emerald-400 transition-colors"
              >
                <span>{tile.title}</span>
                {tile.price_estimate != null && tile.price_estimate > 0 && (
                  <span className="text-zinc-400 dark:text-zinc-500">
                    {'· ~$'}
                    {Math.round(tile.price_estimate)}
                    {'/night'}
                  </span>
                )}
                <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
            ))}
          </div>
        </div>
      )}

      {activityLinks.length > 0 && (
        <div>
          <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-2">Activities</p>
          <div className="flex flex-col gap-1.5">
            {activityLinks.map((block) => (
              <a
                key={block.id}
                href={block.deeplink}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-emerald-500 hover:text-emerald-400 transition-colors"
              >
                {block.summary || block.activity_type || 'Activity'}
              </a>
            ))}
          </div>
        </div>
      )}

      <p className={cn(DS.textSize.micro, 'text-zinc-400 dark:text-zinc-500 mt-3')}>
        Links open Google Travel Hotels and Google Maps
      </p>
    </div>
  );
}
