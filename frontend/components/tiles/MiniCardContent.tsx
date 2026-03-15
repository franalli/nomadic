'use client';

import type { MouseEvent } from 'react';
import { useCallback, useState } from 'react';

import type { Tile } from '@/types/tile';

import { MiniCardQuickFacts } from './MiniCardQuickFacts';
import { MiniCardSummary } from './MiniCardSummary';

export interface MiniCardContentProps {
  tile: Tile;
  isSaved: boolean;
  perks: string[];
  onSaveClick: (e: MouseEvent) => void;
  onOpenStaysSettings?: () => void;
  saveLabel?: string;
}

export function MiniCardContent({
  tile,
  isSaved,
  perks,
  onSaveClick,
  onOpenStaysSettings,
  saveLabel,
}: MiniCardContentProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleQuickFactsToggle = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setIsExpanded((prev) => !prev);
  }, []);

  const quickFactsPanelId = `quickfacts-${tile.id}`;

  return (
    <>
      <MiniCardSummary
        tile={tile}
        isSaved={isSaved}
        perks={perks}
        onSaveClick={onSaveClick}
        onOpenStaysSettings={onOpenStaysSettings}
        saveLabel={saveLabel}
      />
      <MiniCardQuickFacts
        tile={tile}
        isExpanded={isExpanded}
        quickFactsPanelId={quickFactsPanelId}
        onToggle={handleQuickFactsToggle}
      />
    </>
  );
}
