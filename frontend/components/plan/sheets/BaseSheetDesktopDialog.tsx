'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { type MouseEvent,useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/utils';

import {
  BACKDROP_ANIMATE,
  BACKDROP_EXIT,
  BACKDROP_INITIAL,
  BACKDROP_TRANSITION,
  type BaseSheetProps,
  MODAL_ANIMATE,
  MODAL_EXIT,
  MODAL_INITIAL,
  MODAL_TRANSITION,
} from './BaseSheet.shared';

const MAX_WIDTH_CLASS: Record<NonNullable<BaseSheetProps['maxWidth']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '2xl': 'max-w-2xl',
};

export function BaseSheetDesktopDialog({
  open,
  onOpenChange,
  title,
  hint,
  children,
  footer,
  className,
  maxWidth = 'sm',
}: BaseSheetProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onOpenChange(false);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [open, onOpenChange]);

  const handleBackdropClick = useCallback(
    (e: MouseEvent) => {
      if (e.target === e.currentTarget) {
        onOpenChange(false);
      }
    },
    [onOpenChange]
  );

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={BACKDROP_INITIAL}
            animate={BACKDROP_ANIMATE}
            exit={BACKDROP_EXIT}
            transition={BACKDROP_TRANSITION}
            className="fixed inset-0 z-[1200] bg-black/40 backdrop-blur-sm"
            onClick={handleBackdropClick}
          />

          <div
            className="fixed inset-0 z-[1201] flex items-center justify-center p-4"
            onClick={handleBackdropClick}
          >
            <motion.div
              ref={dialogRef}
              initial={MODAL_INITIAL}
              animate={MODAL_ANIMATE}
              exit={MODAL_EXIT}
              transition={MODAL_TRANSITION}
              className={cn(
                'w-full rounded-2xl',
                'bg-white/90 dark:bg-zinc-950/95',
                'backdrop-blur-xl',
                'border border-zinc-200 dark:border-white/10',
                'shadow-2xl shadow-zinc-200/50 dark:shadow-black/80',
                MAX_WIDTH_CLASS[maxWidth]
              )}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between px-5 pt-5 pb-3">
                <div className="flex-1 min-w-0">
                  <h2 className="text-lg font-semibold text-zinc-900 dark:text-white">{title}</h2>
                  {hint && (
                    <p className="mt-0.5 text-xs font-medium text-zinc-500 dark:text-zinc-500">
                      {hint}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onOpenChange(false)}
                  aria-label="Close"
                  className={cn(
                    'p-2 -mr-2 rounded-full',
                    'text-zinc-400 dark:text-zinc-500',
                    'hover:bg-zinc-100 hover:text-zinc-900',
                    'dark:hover:bg-white/10 dark:hover:text-white',
                    'transition-colors duration-150'
                  )}
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className={cn('px-5 pb-3 max-h-[60vh] overflow-y-auto', className)}>
                {children}
              </div>

              {footer && (
                <div className="rounded-b-2xl border-t border-zinc-200 bg-zinc-50/80 px-5 py-4 dark:border-white/5 dark:bg-white/[0.02]">
                  {footer}
                </div>
              )}
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}
