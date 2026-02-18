/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * BaseSheet
 *
 * Shared sheet component for constraint editing.
 * Responsive: uses Dialog on desktop, BottomSheet on mobile.
 *
 * All sheets follow this pattern:
 * - Header: Title + 1-line hint
 * - Content: Sheet-specific inputs
 * - Footer: Save (primary), Cancel, optional Reset
 */

'use client';

import { AnimatePresence, motion, type PanInfo } from 'framer-motion';
import { X } from 'lucide-react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface BaseSheetProps {
  /** Whether the sheet is open */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Sheet title */
  title: string;
  /** Optional hint text below the title */
  hint?: string;
  /** Content to display */
  children: React.ReactNode;
  /** Footer content (Save/Cancel buttons) */
  footer?: React.ReactNode;
  /** Additional className for the content container */
  className?: string;
  /** Max width for desktop dialog */
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl';
}

// ─────────────────────────────────────────────────────────────────────────────
// Desktop Dialog Component
// ─────────────────────────────────────────────────────────────────────────────

function DesktopDialog({
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

  // SSR safety - only render portal on client
  useEffect(() => {
    setMounted(true);
  }, []);

  // Close on escape
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

  // Close on click outside
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) {
        onOpenChange(false);
      }
    },
    [onOpenChange]
  );

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

  const maxWidthClass = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
  }[maxWidth];

  // Don't render portal until mounted (SSR safety)
  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[1200] bg-black/40 backdrop-blur-sm"
            onClick={handleBackdropClick}
          />

          {/* Dialog */}
          <div
            className="fixed inset-0 z-[1201] flex items-center justify-center p-4"
            onClick={handleBackdropClick}
          >
            <motion.div
              ref={dialogRef}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{
                type: 'spring',
                damping: 30,
                stiffness: 400,
              }}
              className={cn(
                'w-full rounded-2xl',
                'bg-white/90 dark:bg-zinc-950/95',
                'backdrop-blur-xl',
                'border border-zinc-200 dark:border-white/10',
                'shadow-2xl shadow-zinc-200/50 dark:shadow-black/80',
                maxWidthClass
              )}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-start justify-between px-5 pt-5 pb-3">
                <div className="flex-1 min-w-0">
                  <h2 className="text-lg font-semibold text-zinc-900 dark:text-white">
                    {title}
                  </h2>
                  {hint && (
                    <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-0.5 font-medium">
                      {hint}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onOpenChange(false)}
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

              {/* Content */}
              <div
                className={cn(
                  'px-5 pb-3 max-h-[60vh] overflow-y-auto',
                  className
                )}
              >
                {children}
              </div>

              {/* Footer */}
              {footer && (
                <div className="px-5 py-4 border-t border-zinc-200 dark:border-white/5 bg-zinc-50/80 dark:bg-white/[0.02] rounded-b-2xl">
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

// ─────────────────────────────────────────────────────────────────────────────
// Mobile Bottom Sheet Component
// ─────────────────────────────────────────────────────────────────────────────

function MobileSheet({
  open,
  onOpenChange,
  title,
  hint,
  children,
  footer,
  className,
}: BaseSheetProps) {
  const [mounted, setMounted] = useState(false);

  // SSR safety - only render portal on client
  useEffect(() => {
    setMounted(true);
  }, []);

  // Close on escape
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

  // Handle drag end
  const handleDragEnd = useCallback(
    (_: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
      if (info.offset.y > 100 || info.velocity.y > 500) {
        onOpenChange(false);
      }
    },
    [onOpenChange]
  );

  // Don't render portal until mounted (SSR safety)
  if (!mounted) return null;

  return createPortal(
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
              // Premium: rounder corners (3xl = 24px radius)
              'max-h-[90vh] overflow-hidden rounded-t-3xl',
              'bg-white/95 dark:bg-zinc-950/95',
              'backdrop-blur-xl',
              'border-t border-zinc-200 dark:border-white/10',
              'shadow-[0_-8px_32px_rgba(0,0,0,0.12)] dark:shadow-[0_-8px_32px_rgba(0,0,0,0.5)]'
            )}
          >
            {/* Drag Handle - larger for better touch affordance */}
            <div className="sticky top-0 z-10 flex justify-center pt-3 pb-2 bg-white/95 dark:bg-zinc-950/95">
              <div className="w-12 h-1.5 rounded-full bg-zinc-300 dark:bg-zinc-700/50" />
            </div>

            {/* Header */}
            <div className="flex items-start justify-between px-4 pb-3">
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-zinc-900 dark:text-white">
                  {title}
                </h2>
                {hint && (
                  <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-0.5 font-medium">
                    {hint}
                  </p>
                )}
              </div>
              {/* Close button with larger hit area for touch */}
              <button
                type="button"
                onClick={() => onOpenChange(false)}
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

            {/* Content - scrollable */}
            <div
              className={cn(
                'px-4 overflow-y-auto',
                'max-h-[calc(85vh-120px)]',
                className
              )}
            >
              {children}
            </div>

            {/* Footer - with iOS safe area padding */}
            {footer && (
              <div className={cn(
                'sticky bottom-0 px-4 py-4',
                'border-t border-zinc-200 dark:border-white/5',
                'bg-white/95 dark:bg-zinc-950/95',
                // Critical: Respect iOS Home Indicator
                'pb-[calc(1rem+env(safe-area-inset-bottom))]'
              )}>
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

// ─────────────────────────────────────────────────────────────────────────────
// Main Component (switches based on screen size)
// ─────────────────────────────────────────────────────────────────────────────

function BaseSheetInner(props: BaseSheetProps) {
  const isDesktop = useIsDesktop();

  if (isDesktop) {
    return <DesktopDialog {...props} />;
  }

  return <MobileSheet {...props} />;
}

export const BaseSheet = memo(BaseSheetInner);

export default BaseSheet;
