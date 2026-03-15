'use client';

import { ChevronDown, Code2 } from 'lucide-react';
import type { MouseEvent } from 'react';
import { useMemo } from 'react';

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { DS } from '@/lib/design-system';
import { getDeepLinkParams } from '@/lib/tileUtils';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { getTileAmenities, getTileCancellationText, getTileCheckTimes } from './tileHelpers';

type MiniCardQuickFactsProps = {
  tile: Tile;
  isExpanded: boolean;
  quickFactsPanelId: string;
  onToggle: (event: MouseEvent<HTMLButtonElement>) => void;
};

export function MiniCardQuickFacts({
  tile,
  isExpanded,
  quickFactsPanelId,
  onToggle,
}: MiniCardQuickFactsProps) {
  const amenities = useMemo(() => getTileAmenities(tile), [tile]);
  const cancellationText = useMemo(() => getTileCancellationText(tile), [tile]);
  const checkTimes = useMemo(() => getTileCheckTimes(tile), [tile]);

  return (
    <>
      <div className="border-t border-zinc-200/50 dark:border-white/10">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={isExpanded}
          aria-controls={quickFactsPanelId}
          className="flex w-full min-h-[44px] items-center gap-1.5 px-3 py-2 text-xs text-zinc-500 transition-colors hover:bg-zinc-100/50 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-zinc-100"
        >
          <ChevronDown
            className={cn('h-3 w-3 transition-transform duration-200', isExpanded && 'rotate-180')}
          />
          <span>Quick facts</span>
        </button>
      </div>

      {isExpanded && (
        <div
          id={quickFactsPanelId}
          className="space-y-2 border-t border-zinc-200/50 px-3 pb-3 pt-2 dark:border-white/10"
        >
          {(cancellationText || checkTimes.checkIn || checkTimes.checkOut) && (
            <div className="space-y-1">
              <h5 className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Key facts
              </h5>
              <ul className="space-y-0.5 text-xs text-zinc-900 dark:text-zinc-100">
                {checkTimes.checkIn && <li>&#8226; Check-in: {checkTimes.checkIn}</li>}
                {checkTimes.checkOut && <li>&#8226; Check-out: {checkTimes.checkOut}</li>}
                {cancellationText && <li>&#8226; {cancellationText}</li>}
              </ul>
            </div>
          )}

          {amenities.length > 0 && (
            <div className="space-y-1">
              <h5 className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Amenities
              </h5>
              <div className="flex flex-wrap gap-1">
                {amenities.slice(0, 4).map((amenity) => (
                  <span
                    key={amenity}
                    className={`rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 ${DS.textSize.micro} text-zinc-600 dark:text-zinc-400`}
                  >
                    {amenity}
                  </span>
                ))}
                {amenities.length > 4 && (
                  <span
                    className={`rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 ${DS.textSize.micro} text-zinc-500/70 dark:text-zinc-400`}
                  >
                    +{amenities.length - 4} more
                  </span>
                )}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between">
            {tile.provider && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">via {tile.provider}</p>
            )}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={(event) => event.stopPropagation()}
                    className={`flex items-center gap-1 rounded px-1.5 py-0.5 ${DS.textSize.micro} text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100`}
                  >
                    <Code2 className="h-3 w-3" />
                    <span>API</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs">
                  <p className={`${DS.textSize.micro} mb-1 font-medium text-zinc-500 dark:text-zinc-400`}>
                    Booking API Payload
                  </p>
                  <pre className={`${DS.textSize.micro} max-h-40 overflow-auto rounded bg-zinc-100/50 p-2 font-mono dark:bg-zinc-800/50`}>
                    {JSON.stringify(getDeepLinkParams(tile), null, 2)}
                  </pre>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      )}
    </>
  );
}
