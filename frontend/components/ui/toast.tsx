'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * Toast System - "System Signals"
 *
 * Toasts follow the **Inversion Rule** for maximum visibility:
 * - Light Mode: "The Black Chip" - Solid zinc-900 background
 * - Dark Mode: "The Emerald Signal" - Deep glass with emerald glow
 *
 * Placement:
 * - Desktop: Bottom-right (system notification tray area)
 * - Mobile: Top-center, safe-area aware (avoids keyboard/chat input)
 *
 * Behavior:
 * - Auto-dismiss after 2s
 * - No layout shift (fixed position)
 * - Stacks up to 3 toasts
 * - Throttles rapid changes (collapse within ~2s)
 */


import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';

import { ToastContainer } from './ToastParts';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type ToastType = 'success' | 'info' | 'warning' | 'error' | 'confirmation';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  duration?: number;
  action?: ToastAction;
}

interface ToastContextValue {
  toast: (message: string, options?: { type?: ToastType; duration?: number; action?: ToastAction }) => void;
  dismiss: (id: string) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

// ─────────────────────────────────────────────────────────────────────────────
// Toast Provider
// ─────────────────────────────────────────────────────────────────────────────

const THROTTLE_WINDOW = 2000; // 2 seconds

interface ToastProviderProps {
  children: React.ReactNode;
}

export function ToastProvider({ children }: ToastProviderProps) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const lastToastRef = useRef<{ message: string; timestamp: number } | null>(null);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (
      message: string,
      options?: { type?: ToastType; duration?: number; action?: ToastAction }
    ) => {
      const now = Date.now();

      // Throttle: if same message within window, skip
      if (
        lastToastRef.current &&
        lastToastRef.current.message === message &&
        now - lastToastRef.current.timestamp < THROTTLE_WINDOW
      ) {
        return;
      }

      // Check for "Preferences updated" consolidation
      // If last toast was a preference update and new one is too, consolidate
      const preferencePatterns = [
        'preferences saved',
        'included',
        'removed',
        'set to',
        'updated',
      ];
      const isPreferenceUpdate = preferencePatterns.some((p) =>
        message.toLowerCase().includes(p)
      );
      const wasPreferenceUpdate =
        lastToastRef.current &&
        preferencePatterns.some((p) =>
          lastToastRef.current!.message.toLowerCase().includes(p)
        );

      // If both are preference updates within throttle window, consolidate
      // Exception: never consolidate toasts that carry an action button (e.g. Undo)
      if (
        isPreferenceUpdate &&
        wasPreferenceUpdate &&
        !options?.action &&
        lastToastRef.current &&
        now - lastToastRef.current.timestamp < THROTTLE_WINDOW
      ) {
        // Replace last toast with consolidated message
        setToasts((prev) => {
          const filtered = prev.filter(
            (t) => t.message !== lastToastRef.current?.message
          );
          const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
          return [
            ...filtered,
            {
              id,
              message: 'Preferences updated',
              type: options?.type ?? 'success',
              duration: options?.duration ?? 2000,
            },
          ];
        });
        lastToastRef.current = { message: 'Preferences updated', timestamp: now };
        return;
      }

      // Create new toast
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const newToast: Toast = {
        id,
        message,
        type: options?.type ?? 'success',
        duration: options?.duration ?? 2000,
        ...(options?.action && { action: options.action }),
      };

      lastToastRef.current = { message, timestamp: now };
      setToasts((prev) => [...prev, newToast]);
    },
    []
  );

  const contextValue = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export { ToastContext };
