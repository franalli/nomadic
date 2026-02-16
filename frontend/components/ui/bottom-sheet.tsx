/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { AnimatePresence, motion, type PanInfo } from 'framer-motion';
import { X } from 'lucide-react';
import { memo, useCallback, useEffect } from 'react';

import { cn } from '@/lib/utils';

interface BottomSheetProps {
  /** Whether the bottom sheet is open */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Title displayed in the header */
  title: string;
  /** Optional hint text below the title */
  hint?: string;
  /** Content to display in the sheet */
  children: React.ReactNode;
  /** Additional className for the content container */
  className?: string;
}

function BottomSheetInner({
  open,
  onOpenChange,
  title,
  hint,
  children,
  className,
}: BottomSheetProps) {
  // Close on escape key
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

  // Prevent body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  // Handle drag end - close if dragged down past threshold
  const handleDragEnd = useCallback(
    (_: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
      // Close if dragged down more than 100px or with enough velocity
      if (info.offset.y > 100 || info.velocity.y > 500) {
        onOpenChange(false);
      }
    },
    [onOpenChange]
  );

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[1200] bg-black/40 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />

          {/* Sheet */}
          <motion.div
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{
              type: 'spring',
              damping: 30,
              stiffness: 300,
            }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.5 }}
            onDragEnd={handleDragEnd}
            className={cn(
              'fixed bottom-0 left-0 right-0 z-[1201]',
              'max-h-[70vh] overflow-hidden rounded-t-2xl',
              'bg-[var(--theme-panel)] border-t border-[var(--theme-border)]',
              'shadow-[0_-4px_24px_rgba(0,0,0,0.12)]',
              'pb-[env(safe-area-inset-bottom)]'
            )}
          >
            {/* Drag Handle */}
            <div className="sticky top-0 z-10 flex justify-center py-3 bg-[var(--theme-panel)]">
              <div className="h-1 w-10 rounded-full bg-[var(--theme-border)]" />
            </div>

            {/* Header */}
            <div className="flex items-start justify-between px-4 pb-3">
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-[var(--theme-text)]">
                  {title}
                </h2>
                {hint && (
                  <p className="text-xs text-[var(--theme-text-muted)] mt-0.5">
                    {hint}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className={cn(
                  'p-2 -mr-2 rounded-full',
                  'text-[var(--theme-text-muted)]',
                  'hover:bg-[var(--theme-overlay)]',
                  'transition-colors duration-150'
                )}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Content - scrollable */}
            <div
              className={cn(
                'px-4 pb-4 overflow-y-auto',
                'max-h-[calc(70vh-80px)]',
                className
              )}
            >
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export const BottomSheet = memo(BottomSheetInner);
