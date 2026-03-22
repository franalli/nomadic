'use client';

/**
 * useUndoStack
 *
 * Exposes the undo entry from documentStore and auto-expires it after 8 seconds.
 * Mount this once near the timeline root so the timer always runs.
 */

import { useEffect, useMemo } from 'react';

import { useDocumentStore } from '@/state/documentStore';

export function useUndoStack() {
  const undoEntry = useDocumentStore(s => s.undoEntry);
  const setUndoEntry = useDocumentStore(s => s.setUndoEntry);
  const executeUndo = useDocumentStore(s => s.executeUndo);

  // Auto-expire after 8 seconds
  useEffect(() => {
    if (!undoEntry) return;
    const timer = setTimeout(() => setUndoEntry(null), 8000);
    return () => clearTimeout(timer);
  }, [undoEntry, setUndoEntry]);

  return useMemo(() => ({ undoEntry, executeUndo }), [undoEntry, executeUndo]);
}
