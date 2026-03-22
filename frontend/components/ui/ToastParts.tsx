'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';
import { memo, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import type { Toast } from './toast';

// ─────────────────────────────────────────────────────────────────────────────
// Toast Animation Constants (hoisted to avoid new object refs per render)
// ─────────────────────────────────────────────────────────────────────────────

const TOAST_INITIAL = { opacity: 0, y: -20, scale: 0.95 };
const TOAST_ANIMATE = { opacity: 1, y: 0, scale: 1 };
const TOAST_EXIT = { opacity: 0, y: -10, scale: 0.95 };
const TOAST_TRANSITION = { type: 'spring' as const, stiffness: 400, damping: 30 };

// ─────────────────────────────────────────────────────────────────────────────
// Toast Item Component
// ─────────────────────────────────────────────────────────────────────────────

interface ToastItemProps {
  toast: Toast;
  onDismiss: (id: string) => void;
}

const ToastItem = memo(function ToastItem({ toast, onDismiss }: ToastItemProps) {
  const { id, message, type, duration = 2000, action } = toast;

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
      initial={TOAST_INITIAL}
      animate={TOAST_ANIMATE}
      exit={TOAST_EXIT}
      transition={TOAST_TRANSITION}
      className={cn(
        // Base shape
        'flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl',
        'font-medium text-sm tracking-wide',
        // Light Mode: "The Black Chip" - Solid zinc-900
        'bg-zinc-900 text-white border border-zinc-800',
        // Dark Mode: "The Emerald Signal" - Deep glass with glow
        'dark:bg-zinc-950/90 dark:backdrop-blur-md dark:text-white',
        'dark:border dark:border-emerald-500/20',
        `dark:${DS.glowClass.md}`
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
        {type === 'confirmation' && (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        )}
      </div>

      {/* Message */}
      <span className="flex-1 min-w-0 break-words">{message}</span>

      {/* Action button (e.g. Undo) */}
      {action && (
        <button
          type="button"
          onClick={() => { action.onClick(); onDismiss(id); }}
          className="flex-shrink-0 text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition-colors px-1"
        >
          {action.label}
        </button>
      )}

      {/* Dismiss button - min 44px touch target per design-system.md */}
      <button
        type="button"
        onClick={() => onDismiss(id)}
        aria-label="Dismiss"
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

export const ToastContainer = memo(function ToastContainer({
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
