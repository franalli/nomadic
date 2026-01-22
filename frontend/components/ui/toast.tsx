/**
 * Toast System
 *
 * Simple toast notifications for constraint updates.
 *
 * Placement:
 * - Desktop: Top-right, fixed position
 * - Mobile: Top-center, safe-area aware
 *
 * Behavior:
 * - Auto-dismiss after 2s
 * - No layout shift (fixed position)
 * - Stacks up to 3 toasts
 * - Throttles rapid changes (collapse within ~2s)
 */

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Check, X } from 'lucide-react';
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

export type ToastType = 'success' | 'info' | 'warning';

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
        'flex items-center gap-2 px-3.5 py-2.5 rounded-lg',
        'shadow-lg backdrop-blur-md',
        'text-sm font-medium',
        // Type-based styling
        type === 'success' && [
          'bg-emerald-500/90 text-white',
          'border border-emerald-400/30',
        ],
        type === 'info' && [
          'bg-zinc-800/90 text-white dark:bg-zinc-700/90',
          'border border-zinc-600/30',
        ],
        type === 'warning' && [
          'bg-amber-500/90 text-white',
          'border border-amber-400/30',
        ]
      )}
    >
      {/* Icon */}
      <div className="flex-shrink-0">
        {type === 'success' && <Check className="h-4 w-4" />}
        {type === 'info' && <Check className="h-4 w-4" />}
        {type === 'warning' && <span className="text-sm">⚠</span>}
      </div>

      {/* Message */}
      <span className="flex-1 min-w-0 truncate">{message}</span>

      {/* Dismiss button */}
      <button
        type="button"
        onClick={() => onDismiss(id)}
        className="flex-shrink-0 p-0.5 rounded-full hover:bg-white/20 transition-colors"
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
        // Desktop: top-right
        'md:top-4 md:right-4',
        // Mobile: top-center, safe-area aware
        'top-[calc(env(safe-area-inset-top)+12px)] left-1/2 -translate-x-1/2 md:left-auto md:translate-x-0'
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
