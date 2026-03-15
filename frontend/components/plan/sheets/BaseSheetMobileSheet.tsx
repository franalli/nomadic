'use client';

import { AnimatePresence, motion, type PanInfo } from 'framer-motion';
import { X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/utils';

import {
  BACKDROP_ANIMATE,
  BACKDROP_EXIT,
  BACKDROP_INITIAL,
  type BaseSheetProps,
  MOBILE_BACKDROP_TRANSITION,
  MOBILE_SHEET_ANIMATE,
  MOBILE_SHEET_EXIT,
  MOBILE_SHEET_INITIAL,
  MOBILE_SHEET_TRANSITION,
} from './BaseSheet.shared';

export function BaseSheetMobileSheet({
  open,
  onOpenChange,
  title,
  hint,
  children,
  footer,
  className,
}: BaseSheetProps) {
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

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  const handleDragEnd = useCallback(
    (_: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
      if (info.offset.y > 100 || info.velocity.y > 500) {
        onOpenChange(false);
      }
    },
    [onOpenChange]
  );

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={BACKDROP_INITIAL}
            animate={BACKDROP_ANIMATE}
            exit={BACKDROP_EXIT}
            transition={MOBILE_BACKDROP_TRANSITION}
            className="fixed inset-0 z-[1200] bg-black/40 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />

          <motion.div
            initial={MOBILE_SHEET_INITIAL}
            animate={MOBILE_SHEET_ANIMATE}
            exit={MOBILE_SHEET_EXIT}
            transition={MOBILE_SHEET_TRANSITION}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.5 }}
            onDragEnd={handleDragEnd}
            className={cn(
              'fixed bottom-0 left-0 right-0 z-[1201]',
              'max-h-[90vh] overflow-hidden rounded-t-3xl',
              'bg-white/95 dark:bg-zinc-950/95',
              'backdrop-blur-xl',
              'border-t border-zinc-200 dark:border-white/10',
              'shadow-soft'
            )}
          >
            <div className="sticky top-0 z-10 flex justify-center bg-white/95 pt-3 pb-2 dark:bg-zinc-950/95">
              <div className="h-1.5 w-12 rounded-full bg-zinc-300 dark:bg-zinc-700/50" />
            </div>

            <div className="flex items-start justify-between px-4 pb-3">
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-zinc-900 dark:text-white">{title}</h2>
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
                  'p-3 -mr-3 rounded-full',
                  'text-zinc-400 dark:text-zinc-500',
                  'hover:bg-zinc-100 hover:text-zinc-900',
                  'dark:hover:bg-white/10 dark:hover:text-white',
                  'transition-colors duration-150'
                )}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className={cn('max-h-[calc(85vh-120px)] overflow-y-auto px-4', className)}>
              {children}
            </div>

            {footer && (
              <div
                className={cn(
                  'sticky bottom-0 border-t border-zinc-200 bg-white/95 px-4 py-4 dark:border-white/5 dark:bg-zinc-950/95',
                  'pb-[calc(1rem+env(safe-area-inset-bottom))]'
                )}
              >
                {footer}
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}
