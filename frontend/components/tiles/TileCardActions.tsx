'use client';

import { ExternalLink, MapPin } from 'lucide-react';
import type { MouseEvent } from 'react';

import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { DS } from '@/lib/design-system';
import { getDeepLinkParams } from '@/lib/tileUtils';
import { cn } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

import {
  getEffectiveTileDeeplinkUrl,
  getTileDeeplinkPillLabel,
  isPartnerDeeplinkUrl,
} from './tileHelpers';

type TileCardActionsProps = {
  tile: Tile;
  onViewDetailsClick: (event: MouseEvent) => void;
};

export function TileCardActions({ tile, onViewDetailsClick }: TileCardActionsProps) {
  const tripInputs = useDocumentTripInputs();
  const deeplinkUrl = getEffectiveTileDeeplinkUrl(tile, tripInputs);

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        <TooltipProvider delayDuration={400}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white"
                onClick={onViewDetailsClick}
              >
                Details
              </Button>
            </TooltipTrigger>
            <TooltipContent
              side="top"
              className="max-w-xs rounded-lg bg-zinc-900 p-3 text-xs font-mono text-zinc-100 shadow-2xl"
            >
              <div className={`mb-1.5 text-zinc-400 ${DS.textSize.micro} uppercase tracking-wider`}>
                API Params
              </div>
              <pre className="whitespace-pre-wrap break-all">
                {JSON.stringify(getDeepLinkParams(tile), null, 2)}
              </pre>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        {deeplinkUrl && deeplinkUrl !== '#' && (() => {
          const isPartner = isPartnerDeeplinkUrl(deeplinkUrl);
          return (
            <a
              href={deeplinkUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(event) => event.stopPropagation()}
              className={cn(
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                'text-xs font-bold uppercase tracking-wide',
                'transition-all duration-150 active:scale-95',
                'bg-emerald-50 border border-emerald-500/30 text-emerald-700',
                'hover:bg-emerald-100 hover:border-emerald-500/60',
                'dark:bg-emerald-950/40 dark:border-emerald-500/25 dark:text-emerald-400',
                'dark:hover:bg-emerald-900/50 dark:hover:border-emerald-400/50',
                `dark:hover:${DS.glowClass.chipHoverLg}`
              )}
            >
              {isPartner ? <ExternalLink className="h-3.5 w-3.5" /> : <MapPin className="h-3.5 w-3.5" />}
              {getTileDeeplinkPillLabel(tile, deeplinkUrl)}
            </a>
          );
        })()}
      </div>
    </div>
  );
}
