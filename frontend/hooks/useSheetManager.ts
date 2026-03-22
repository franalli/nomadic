'use client';

/**
 * useSheetManager
 *
 * Single activeSheet state management hook.
 * Benefits: No state explosion, no "close all others" logic, easy reset via closeSheet().
 *
 * Host this at the lowest common parent that renders both PlanHeader and ChatPanel
 * (e.g., StrategyStageRenderer or NomadicLanding).
 */

import { useCallback, useMemo, useState } from 'react';

import type { SheetType } from '@/types/sheets';

export function useSheetManager() {
  const [activeSheet, setActiveSheet] = useState<SheetType | null>(null);

  const openSheet = useCallback((sheet: SheetType) => setActiveSheet(sheet), []);
  const closeSheet = useCallback(() => setActiveSheet(null), []);

  return useMemo(() => ({ activeSheet, openSheet, closeSheet }), [activeSheet, openSheet, closeSheet]);
}
