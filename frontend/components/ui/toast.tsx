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

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type ToastType = 'success' | 'info' | 'warning' | 'error';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  duration?: number;
}

interface ToastContextValue {
  toast: (message: string, options?: { type?: ToastType; duration?: number }) => void;
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
// Toast Item Component
// ─────────────────────────────────────────────────────────────────────────────

interface ToastItemProps {
  toast: Toast;
  onDismiss: (id: string) => void;
}

const ToastItem = memo(function ToastItem({ toast, onDismiss }: ToastItemProps) {
  const { id, message, type, duration = 2000 } = toast;

  // Auto dismiss
  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss(id);
    }, duration);

    return () => clearTimeout(timer);
  }, [id, duration, onDismiss]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -10, scale: 0.95 }}
      transition={{
        type: 'spring',
        stiffness: 400,
        damping: 30,
      }}
      className={cn(
        // Base shape
        'flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl',
        'font-medium text-sm tracking-wide',
        // Light Mode: "The Black Chip" - Solid zinc-900
        'bg-zinc-900 text-white border border-zinc-800',
        // Dark Mode: "The Emerald Signal" - Deep glass with glow
        'dark:bg-zinc-950/90 dark:backdrop-blur-md dark:text-white',
        'dark:border dark:border-emerald-500/20',
        'dark:shadow-[0_0_20px_-5px_rgba(16,185,129,0.3)]'
      )}
    >
      {/* Icon - colored by type */}
      <div className="flex-shrink-0">
        {type === 'success' && (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        )}
        {type === 'info' && (
          <Info className="h-4 w-4 text-zinc-400" />
        )}
        {type === 'warning' && (
          <AlertCircle className="h-4 w-4 text-amber-400" />
        )}
        {type === 'error' && (
          <AlertCircle className="h-4 w-4 text-red-400" />
        )}
      </div>

      {/* Message */}
      <span className="flex-1 min-w-0 break-words">{message}</span>

      {/* Dismiss button - min 44px touch target per design-system.md */}
      <button
        type="button"
        onClick={() => onDismiss(id)}
        className="flex-shrink-0 p-2 -m-1 rounded-full hover:bg-white/20 transition-colors"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </motion.div>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Toast Container
// ─────────────────────────────────────────────────────────────────────────────

interface ToastContainerProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

const ToastContainer = memo(function ToastContainer({
  toasts,
  onDismiss,
}: ToastContainerProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  const container = document.getElementById('toast-portal') || document.body;

  return createPortal(
    <div
      className={cn(
        'fixed z-[9999] pointer-events-none',
        // Desktop: bottom-right (system notification tray area)
        'md:bottom-8 md:right-8 md:top-auto md:left-auto md:translate-x-0',
        // Mobile: top-center, safe-area aware (avoids keyboard/chat input)
        'top-[calc(env(safe-area-inset-top)+16px)] left-1/2 -translate-x-1/2',
        // Mobile width constraint — never exceed viewport
        'w-[calc(100vw-32px)] md:w-auto md:max-w-sm'
      )}
    >
      <div className="flex flex-col gap-2 items-end pointer-events-auto">
        <AnimatePresence mode="popLayout" initial={false}>
          {toasts.slice(0, 3).map((toast) => (
            <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
          ))}
        </AnimatePresence>
      </div>
    </div>,
    container
  );
});

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
      options?: { type?: ToastType; duration?: number }
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
      if (
        isPreferenceUpdate &&
        wasPreferenceUpdate &&
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
      };

      lastToastRef.current = { message, timestamp: now };
      setToasts((prev) => [...prev, newToast]);
    },
    []
  );

  return (
    <ToastContext.Provider value={{ toast, dismiss }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Export hook for convenience
// ─────────────────────────────────────────────────────────────────────────────

export { ToastContext };
