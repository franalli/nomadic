import { create } from 'zustand';

interface PanelToggleState {
  staysExpanded: boolean;
  flightsExpanded: boolean;
  activitiesExpanded: boolean;
  intelExpanded: boolean;
  travelAdviceCount: number;
  showTravelAdvice: boolean;
  isTravelAdvicePending: boolean;
  toggleStays: () => void;
  toggleFlights: () => void;
  toggleActivities: () => void;
  toggleIntel: () => void;
  setTravelAdviceData: (data: { count: number; show: boolean; pending: boolean }) => void;
  reset: () => void;
}

export const usePanelToggleStore = create<PanelToggleState>((set) => ({
  staysExpanded: false,
  flightsExpanded: false,
  activitiesExpanded: false,
  intelExpanded: false,
  travelAdviceCount: 0,
  showTravelAdvice: false,
  isTravelAdvicePending: false,
  toggleStays: () => set((s) => ({
    staysExpanded: !s.staysExpanded,
    ...(!s.staysExpanded
      ? { flightsExpanded: false, activitiesExpanded: false, intelExpanded: false }
      : {}),
  })),
  toggleFlights: () => set((s) => ({
    flightsExpanded: !s.flightsExpanded,
    ...(!s.flightsExpanded
      ? { staysExpanded: false, activitiesExpanded: false, intelExpanded: false }
      : {}),
  })),
  toggleActivities: () => set((s) => ({
    activitiesExpanded: !s.activitiesExpanded,
    ...(!s.activitiesExpanded
      ? { staysExpanded: false, flightsExpanded: false, intelExpanded: false }
      : {}),
  })),
  toggleIntel: () => set((s) => ({
    intelExpanded: !s.intelExpanded,
    ...(!s.intelExpanded
      ? { staysExpanded: false, flightsExpanded: false, activitiesExpanded: false }
      : {}),
  })),
  setTravelAdviceData: ({ count, show, pending }) =>
    set({ travelAdviceCount: count, showTravelAdvice: show, isTravelAdvicePending: pending }),
  reset: () =>
    set({
      staysExpanded: false,
      flightsExpanded: false,
      activitiesExpanded: false,
      intelExpanded: false,
      travelAdviceCount: 0,
      showTravelAdvice: false,
      isTravelAdvicePending: false,
    }),
}));
