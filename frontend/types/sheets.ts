/**
 * Canonical SheetType definition
 *
 * Single source of truth for sheet types - prevents drift/mismatch.
 * Import this everywhere: useSheetManager.ts, TripSummaryPills.tsx, PlanHeader.tsx, ChatPanel.tsx
 */

export type SheetType = 'destination' | 'origin' | 'dates' | 'travelers' | 'budget' | 'trip-settings' | 'activities';
