import { create } from 'zustand';

interface MapSyncState {
  // Timeline → Map
  visibleDayNumber: number | null;
  setVisibleDayNumber: (day: number | null) => void;

  // Map → Timeline
  scrollTargetDayNumber: number | null;
  scrollTargetBlockId: string | null;
  requestScrollTo: (day: number, blockId?: string) => void;
  clearScrollTarget: () => void;

  // Highlight ring (after pin click → scroll)
  highlightedCardId: string | null;
  setHighlightedCardId: (id: string | null) => void;
}

export const useMapSync = create<MapSyncState>((set) => ({
  visibleDayNumber: null,
  setVisibleDayNumber: (day) => set({ visibleDayNumber: day }),

  scrollTargetDayNumber: null,
  scrollTargetBlockId: null,
  requestScrollTo: (day, blockId) => set({
    scrollTargetDayNumber: day,
    scrollTargetBlockId: blockId ?? null,
  }),
  clearScrollTarget: () => set({
    scrollTargetDayNumber: null,
    scrollTargetBlockId: null,
  }),

  highlightedCardId: null,
  setHighlightedCardId: (id) => set({ highlightedCardId: id }),
}));
