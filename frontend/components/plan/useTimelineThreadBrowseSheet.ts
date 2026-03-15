'use client';

import { useCallback, useState } from 'react';

import { apiFetch, type BrowseTile } from '@/lib/api';
import { useDocumentStore } from '@/state/documentStore';

interface BrowseSheetDay {
  dayNumber?: number;
  date?: string | null;
}

interface UseTimelineThreadBrowseSheetResult {
  browseSheetOpen: boolean;
  browseSheetDay: BrowseSheetDay | null;
  browseableActivities: Array<Record<string, unknown>>;
  setBrowseSheetOpen: (open: boolean) => void;
  handleBrowse: (dayNumber: number, date: string | null) => void;
  handleSelectActivity: (tile: BrowseTile) => Promise<void>;
}

export function useTimelineThreadBrowseSheet(): UseTimelineThreadBrowseSheetResult {
  const [browseSheetOpen, setBrowseSheetOpen] = useState(false);
  const [browseSheetDay, setBrowseSheetDay] = useState<BrowseSheetDay | null>(null);
  const browseableActivities = useDocumentStore((s) => s.browseableActivities);

  const handleSelectActivity = useCallback(async (tile: BrowseTile) => {
    const targetDay = browseSheetDay?.dayNumber;
    if (!targetDay) return;

    setBrowseSheetOpen(false);

    const { document: currentDoc } = useDocumentStore.getState();
    if (!currentDoc) return;

    try {
      const res = await apiFetch('/api/document/insert-activity-block', {
        method: 'POST',
        body: JSON.stringify({
          day_number: targetDay,
          tile,
        }),
      });
      if (!res.ok) return;
      const result = await res.json();
      const doc = useDocumentStore.getState().document;
      if (!doc) return;
      const updatedDayCards = (doc.day_cards ?? []).map((dc) =>
        dc.day_number === targetDay ? result.day_card : dc
      );
      useDocumentStore.setState({
        document: { ...doc, day_cards: updatedDayCards },
        version: result.version,
      });
    } catch {
      // Silent fail -- the itinerary wasn't modified
    }
  }, [browseSheetDay]);

  const handleBrowse = useCallback((dayNumber: number, date: string | null) => {
    setBrowseSheetDay({ dayNumber, date });
    setBrowseSheetOpen(true);
  }, []);

  return {
    browseSheetOpen,
    browseSheetDay,
    browseableActivities,
    setBrowseSheetOpen,
    handleBrowse,
    handleSelectActivity,
  };
}
