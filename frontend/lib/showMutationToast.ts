/**
 * showMutationToast
 *
 * Shows a toast with an "Undo" action button for destructive mutations.
 * The undo entry must be set in documentStore before calling this.
 * Auto-expires after 8 seconds (matches useUndoStack timer).
 */

import type { ToastAction, ToastType } from '@/components/ui/toast';
import { useDocumentStore } from '@/state/documentStore';

type ToastFn = (message: string, options?: { type?: ToastType; duration?: number; action?: ToastAction }) => void;

export function showMutationToast(label: string, toast: ToastFn): void {
  toast(label, {
    type: 'success',
    duration: 8000,
    action: {
      label: 'Undo',
      onClick: () => {
        useDocumentStore.getState().executeUndo();
      },
    },
  });
}
