'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */

import { differenceInDays } from 'date-fns/differenceInDays';
import { format } from 'date-fns/format';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';
import type { DateRange } from 'react-day-picker';
import { createPortal } from 'react-dom';

import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import { DATE_PRESETS, type DatePreset } from './datePresets';
import { CalendarSection, FooterActions, PresetPillRow } from './DatesSheetParts';

interface DatesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  startDate?: Date | null;
  endDate?: Date | null;
  onSave: (startDate: Date, endDate: Date) => void;
}

const BACKDROP_INITIAL = { opacity: 0 };
const BACKDROP_ANIMATE = { opacity: 1 };
const BACKDROP_EXIT = { opacity: 0 };
const BACKDROP_TRANSITION = { duration: 0.15 };
const MODAL_INITIAL = { opacity: 0, scale: 0.95, y: 10 };
const MODAL_ANIMATE = { opacity: 1, scale: 1, y: 0 };
const MODAL_EXIT = { opacity: 0, scale: 0.95, y: 10 };
const MODAL_TRANSITION = { type: 'spring' as const, damping: 30, stiffness: 400 };

function DatesSheetInner({
  open,
  onOpenChange,
  startDate,
  endDate,
  onSave,
}: DatesSheetProps) {
  const { toast } = useToast();
  const isDesktop = useIsDesktop();
  const [range, setRange] = useState<DateRange | undefined>(undefined);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (open) {
      if (startDate && endDate) {
        setRange({ from: startDate, to: endDate });
      } else {
        setRange(undefined);
      }
      setActivePreset(null);
    }
  }, [open, startDate, endDate]);

  useEffect(() => {
    if (!open) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [open, onOpenChange]);

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  const nights = range?.from && range?.to ? differenceInDays(range.to, range.from) : 0;
  const durationDisplay = (() => {
    if (!range?.from || !range?.to) return 'Select dates';
    const days = nights + 1;
    return `${format(range.from, 'MMM d')} — ${format(range.to, 'MMM d')} (${days} Day${days !== 1 ? 's' : ''})`;
  })();

  const handleSave = useCallback(() => {
    if (!range?.from || !range?.to) return;
    onSave(range.from, range.to);
    toast(`Dates set: ${format(range.from, 'MMM d')}–${format(range.to, 'MMM d')}`);
    onOpenChange(false);
  }, [range, onSave, toast, onOpenChange]);

  const handlePreset = useCallback((preset: DatePreset) => {
    const { from, to } = preset.getDates();
    setRange({ from, to });
    setActivePreset(preset.label);
  }, []);

  const handleSelect = useCallback((newRange: DateRange | undefined) => {
    setRange(newRange);
    setActivePreset(null);
  }, []);

  const handleClear = useCallback(() => {
    setRange(undefined);
    setActivePreset(null);
  }, []);

  const canSave = !!(range?.from && range?.to);

  if (!mounted) return null;

  const content = (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={BACKDROP_INITIAL}
            animate={BACKDROP_ANIMATE}
            exit={BACKDROP_EXIT}
            transition={BACKDROP_TRANSITION}
            className="fixed inset-0 z-[1200] bg-black/60 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />

          <div
            className="fixed inset-0 z-[1201] flex items-center justify-center p-4"
            onClick={(e) => e.target === e.currentTarget && onOpenChange(false)}
          >
            <motion.div
              initial={MODAL_INITIAL}
              animate={MODAL_ANIMATE}
              exit={MODAL_EXIT}
              transition={MODAL_TRANSITION}
              className={cn(
                'relative max-w-2xl w-full',
                'p-0 gap-0 overflow-hidden',
                'rounded-2xl',
                'bg-white/95 dark:bg-zinc-950/95',
                'backdrop-blur-xl',
                'border border-zinc-200 dark:border-white/10',
                'shadow-soft',
                !isDesktop && 'max-w-[95vw]'
              )}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                aria-label="Close"
                className={cn(
                  'absolute right-4 top-4 z-50',
                  'p-2 rounded-full',
                  'text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100',
                  'dark:text-zinc-500 dark:hover:text-white dark:hover:bg-white/10',
                  'transition-all'
                )}
              >
                <X className="w-5 h-5" />
              </button>

              <div className="pt-6 px-6 pb-4 border-b border-zinc-100 dark:border-white/5">
                <h2 className={cn(DS.text.label, 'mb-4')}>Timeline</h2>
                <PresetPillRow
                  presets={DATE_PRESETS}
                  activePreset={activePreset}
                  onPreset={handlePreset}
                />
              </div>

              <CalendarSection
                range={range}
                onSelect={handleSelect}
                isDesktop={isDesktop}
              />

              <FooterActions
                durationDisplay={durationDisplay}
                canSave={canSave}
                hasRange={!!range}
                onClear={handleClear}
                onSave={handleSave}
              />
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );

  return createPortal(content, document.body);
}

export const DatesSheet = memo(DatesSheetInner);

export default DatesSheet;
