'use client';

import { ExternalLink, Heart, Lock } from 'lucide-react';

import { cn } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { getEffectiveTileDeeplinkUrl, getTileDeeplinkActionLabel } from './tileHelpers';

type TileDetailsFooterProps = {
  tile: Tile;
  isSaved: boolean;
  isBookingUnlocked: boolean;
  onSaveClick: () => void;
  onClose: () => void;
  onOpenSheet?: (sheet: SheetType) => void;
};

export function TileDetailsFooter({
  tile,
  isSaved,
  isBookingUnlocked,
  onSaveClick,
  onClose,
  onOpenSheet,
}: TileDetailsFooterProps) {
  const tripInputs = useDocumentTripInputs();
  const deeplinkUrl = getEffectiveTileDeeplinkUrl(tile, tripInputs);
  const deeplinkLabel = getTileDeeplinkActionLabel(tile, deeplinkUrl);

  return (
    <div className="sticky bottom-0 border-t border-zinc-200 bg-white p-4 dark:border-white/10 dark:bg-zinc-900">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onSaveClick}
          className={cn(
            'flex flex-1 items-center justify-center gap-2 rounded-lg py-2.5 font-medium transition-colors',
            isSaved
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'bg-zinc-100 text-zinc-800 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700'
          )}
        >
          <Heart className={cn('h-4 w-4', isSaved && 'fill-emerald-400')} />
          {isSaved ? 'Saved to shortlist' : 'Add to shortlist'}
        </button>
      </div>

      {deeplinkUrl && deeplinkUrl !== '#' && (
        <button
          type="button"
          onClick={() => window.open(deeplinkUrl, '_blank', 'noopener,noreferrer')}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-500 py-2.5 font-medium text-white transition-colors hover:bg-emerald-600"
        >
          {deeplinkLabel}
          <ExternalLink className="h-3.5 w-3.5" />
        </button>
      )}

      {!isBookingUnlocked && (
        <div className="mt-4 space-y-2">
          {onOpenSheet ? (
            <button
              type="button"
              onClick={() => {
                onOpenSheet('dates');
                onClose();
              }}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-zinc-200 bg-zinc-100 py-2 text-sm font-medium text-zinc-800 transition-colors hover:bg-zinc-200 dark:border-white/10 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
            >
              <Lock className="h-3 w-3" />
              Set trip dates to unlock booking
            </button>
          ) : (
            <p className="text-center text-xs text-zinc-500 dark:text-zinc-400">
              Set trip dates and create your itinerary to unlock booking links.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
