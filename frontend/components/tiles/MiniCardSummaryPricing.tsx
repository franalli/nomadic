'use client';

import { ExternalLink, MapPin } from 'lucide-react';
import { useMemo } from 'react';

import { DS } from '@/lib/design-system';
import { formatTilePrice } from '@/lib/format-utils';
import { cn, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { getTileDeeplinkPillLabel, isPartnerDeeplinkUrl } from './tileHelpers';

type MiniCardSummaryPricingProps = {
  tile: Tile;
};

export function MiniCardSummaryPricing({ tile }: MiniCardSummaryPricingProps) {
  const priceDisplay = useMemo(() => formatTilePrice(tile), [tile]);
  const isFlight = isFlightType(tile.type || '');
  const meta = tile.meta as Record<string, unknown> | undefined;
  const logicHook = typeof meta?.logic_hook === 'string' ? meta.logic_hook : undefined;

  return (
    <>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {priceDisplay}
        </span>
        {tile.deeplink_url && tile.deeplink_url !== '#' && (
          <a
            href={tile.deeplink_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(event) => event.stopPropagation()}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5',
              `${DS.textSize.micro} font-bold uppercase tracking-wider`,
              'border border-emerald-500/30 bg-emerald-50 text-emerald-700',
              'transition-all duration-150 active:scale-95 hover:border-emerald-500/60 hover:bg-emerald-100',
              'dark:border-emerald-500/25 dark:bg-emerald-950/40 dark:text-emerald-400',
              'dark:hover:border-emerald-400/50 dark:hover:bg-emerald-900/50',
              'dark:hover:shadow-[0_0_12px_-3px_rgba(16,185,129,0.3)]'
            )}
          >
            {isPartnerDeeplinkUrl(tile.deeplink_url) ? (
              <ExternalLink className="h-3 w-3" />
            ) : (
              <MapPin className="h-3 w-3" />
            )}
            {getTileDeeplinkPillLabel(tile)}
          </a>
        )}
      </div>

      {isFlight && logicHook && (
        <div className="mt-2">
          <span
            className={cn(
              `inline-flex items-center gap-1 rounded px-1.5 py-0.5 ${DS.textSize.micro} font-medium`,
              meta?.is_safe === false
                ? 'border border-zinc-500/20 bg-zinc-500/15 text-zinc-400'
                : 'border border-emerald-500/20 bg-emerald-500/15 text-emerald-400'
            )}
          >
            {logicHook}
          </span>
        </div>
      )}
    </>
  );
}
