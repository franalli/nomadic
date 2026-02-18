/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * DatesSheet
 *
 * Premium date picker - clean, headless design.
 * Deep glass material with emerald accents.
 * Pills as header, floating close button.
 */

'use client';

import { addDays, differenceInDays, format, isBefore, startOfDay } from 'date-fns';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';
import { DateRange } from 'react-day-picker';
import { createPortal } from 'react-dom';

import { Calendar as CalendarComponent } from '@/components/ui/calendar';
import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface DatesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  startDate?: Date | null;
  endDate?: Date | null;
  onSave: (startDate: Date, endDate: Date) => void;
}

// Quick presets
const DATE_PRESETS = [
  { label: 'This Weekend', getDates: () => getThisWeekend() },
  { label: 'Next Week', getDates: () => getNextWeekend() },
  { label: '1 Week', getDates: () => getWeekFromNow(1) },
  { label: '2 Weeks', getDates: () => getWeekFromNow(2) },
];

function getThisWeekend(): { from: Date; to: Date } {
  const today = startOfDay(new Date());
  const dayOfWeek = today.getDay();
  const daysUntilSaturday = (6 - dayOfWeek + 7) % 7 || 7;
  const saturday = addDays(today, daysUntilSaturday);
  const sunday = addDays(saturday, 1);
  return { from: saturday, to: sunday };
}

function getNextWeekend(): { from: Date; to: Date } {
  const thisWeekend = getThisWeekend();
  return { from: addDays(thisWeekend.from, 7), to: addDays(thisWeekend.to, 7) };
}

function getWeekFromNow(weeks: number): { from: Date; to: Date } {
  const today = startOfDay(new Date());
  const from = addDays(today, 1);
  const to = addDays(from, weeks * 7 - 1);
  return { from, to };
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

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

  // SSR safety
  useEffect(() => {
    setMounted(true);
  }, []);

  // Initialize from props when opened
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

  // Close on escape
  useEffect(() => {
    if (!open) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [open, onOpenChange]);

  // Prevent body scroll
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

  // Computed values
  const nights = range?.from && range?.to ? differenceInDays(range.to, range.from) : 0;
  const days = nights + 1;

  // Format duration display
  const durationDisplay = (() => {
    if (!range?.from || !range?.to) return 'Select dates';
    const fromStr = format(range.from, 'MMM d');
    const toStr = format(range.to, 'MMM d');
    return `${fromStr} — ${toStr} (${days} Day${days !== 1 ? 's' : ''})`;
  })();

  // Handle save
  const handleSave = useCallback(() => {
    if (!range?.from || !range?.to) return;
    onSave(range.from, range.to);
    toast(`Dates set: ${format(range.from, 'MMM d')}–${format(range.to, 'MMM d')}`);
    onOpenChange(false);
  }, [range, onSave, toast, onOpenChange]);

  // Handle preset click
  const handlePreset = useCallback((preset: (typeof DATE_PRESETS)[0]) => {
    const { from, to } = preset.getDates();
    setRange({ from, to });
    setActivePreset(preset.label);
  }, []);

  // Handle calendar select
  const handleSelect = useCallback((newRange: DateRange | undefined) => {
    setRange(newRange);
    setActivePreset(null);
  }, []);

  // Handle clear
  const handleClear = useCallback(() => {
    setRange(undefined);
    setActivePreset(null);
  }, []);

  const canSave = range?.from && range?.to;
  const today = startOfDay(new Date());

  if (!mounted) return null;

  const content = (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[1200] bg-black/60 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />

          {/* THE GLASS MONOLITH */}
          <div
            className="fixed inset-0 z-[1201] flex items-center justify-center p-4"
            onClick={(e) => e.target === e.currentTarget && onOpenChange(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ type: 'spring', damping: 30, stiffness: 400 }}
              className={cn(
                // SIZE & SHAPE
                'relative max-w-2xl w-full',
                'p-0 gap-0 overflow-hidden',
                'rounded-2xl',
                // MATERIAL: White Paper (Light) / Deep Glass (Dark)
                'bg-white/95 dark:bg-zinc-950/95',
                'backdrop-blur-xl',
                'border border-zinc-200 dark:border-white/10',
                'shadow-[0_20px_50px_rgba(0,0,0,0.1)] dark:shadow-2xl dark:shadow-black/80',
                // Mobile
                !isDesktop && 'max-w-[95vw]'
              )}
              onClick={(e) => e.stopPropagation()}
            >
              {/* FLOATING CLOSE BUTTON */}
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className={cn(
                  'absolute right-4 top-4 z-50',
                  'p-2 rounded-full',
                  'text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100',
                  'dark:text-zinc-500 dark:hover:text-white dark:hover:bg-white/10',
                  'transition-all'
                )}
              >
                <X className="w-4 h-4" />
              </button>

              {/* ═══════════════════════════════════════════════════════════════ */}
              {/* SECTION 1: HEADER + QUICK SELECTORS */}
              {/* ═══════════════════════════════════════════════════════════════ */}
              <div className="pt-6 px-6 pb-4 border-b border-zinc-100 dark:border-white/5">
                {/* Header */}
                <h2 className={cn(DS.text.label, 'mb-4')}>
                  Timeline
                </h2>
                {/* Quick Select Pills - High Contrast Wireframe Look */}
                <div className="flex flex-wrap gap-2">
                  {DATE_PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => handlePreset(preset)}
                      className={cn(
                        `px-3 py-1.5 rounded-lg ${DS.textSize.micro} font-bold uppercase tracking-wide`,
                        'transition-all duration-200',
                        activePreset === preset.label
                          // Selected: Solid Black (Light) / Solid White (Dark)
                          ? 'bg-zinc-900 text-white border-2 border-transparent dark:bg-white dark:text-black dark:border-transparent shadow-md'
                          // Unselected: White with border
                          : cn(
                              'bg-white border-2 border-zinc-200 dark:border-2 dark:border-white/15',
                              'dark:bg-white/5',
                              'text-zinc-600 dark:text-zinc-400',
                              'hover:border-zinc-900 hover:bg-zinc-50 dark:hover:border-white/40 dark:hover:bg-white/5'
                            )
                      )}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* ═══════════════════════════════════════════════════════════════ */}
              {/* SECTION 2: CALENDAR BODY */}
              {/* ═══════════════════════════════════════════════════════════════ */}
              <div
                className={cn(
                  'p-6 w-full flex justify-center',
                  !isDesktop && 'overflow-x-auto'
                )}
              >
                <CalendarComponent
                  mode="range"
                  selected={range}
                  onSelect={handleSelect}
                  numberOfMonths={isDesktop ? 2 : 1}
                  disabled={(date) => isBefore(date, today)}
                  className="p-0"
                />
              </div>

              {/* ═══════════════════════════════════════════════════════════════ */}
              {/* SECTION 3: FOOTER */}
              {/* ═══════════════════════════════════════════════════════════════ */}
              <div className={cn(
                'p-4 px-6 flex items-center justify-between',
                'border-t border-zinc-100 dark:border-white/5',
                'bg-zinc-50/50 dark:bg-zinc-900/50'
              )}>
                {/* Selection Display */}
                <div className="flex flex-col">
                  <span className={cn(DS.text.label, 'mb-0.5')}>
                    Selection
                  </span>
                  <span className="text-sm font-bold text-zinc-900 dark:text-white tracking-wide">
                    {durationDisplay}
                  </span>
                </div>

                {/* Actions */}
                <div className="flex gap-2 items-center">
                  {range && (
                    <button
                      type="button"
                      onClick={handleClear}
                      className={cn(
                        'px-4 py-2 text-xs font-bold transition-colors',
                        'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'
                      )}
                    >
                      Clear
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={!canSave}
                    className={cn(
                      canSave ? DS.actions.primary : DS.actions.primaryDisabled,
                      'px-6 py-2.5 text-xs uppercase tracking-widest active:scale-95'
                    )}
                  >
                    Apply Dates
                  </button>
                </div>
              </div>
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
