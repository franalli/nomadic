'use client';

import { isBefore } from 'date-fns/isBefore';
import { startOfDay } from 'date-fns/startOfDay';
import type { DateRange } from 'react-day-picker';

import { Calendar as CalendarComponent } from '@/components/ui/calendar';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import type { DatePreset } from './datePresets';

// ─────────────────────────────────────────────────────────────────────────────
// PresetPillRow
// ─────────────────────────────────────────────────────────────────────────────

interface PresetPillRowProps {
  presets: DatePreset[];
  activePreset: string | null;
  onPreset: (preset: DatePreset) => void;
}

export function PresetPillRow({ presets, activePreset, onPreset }: PresetPillRowProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {presets.map((preset) => (
        <button
          key={preset.label}
          type="button"
          onClick={() => onPreset(preset)}
          className={cn(
            `px-3 py-1.5 rounded-lg ${DS.textSize.micro} font-bold uppercase tracking-wide`,
            'transition-all duration-200',
            activePreset === preset.label
              ? 'bg-zinc-900 text-white border-2 border-transparent dark:bg-white dark:text-black dark:border-transparent shadow-md'
              : cn(
                  'bg-white border-2 border-zinc-200 dark:border-2 dark:border-white/15',
                  'dark:bg-white/5',
                  'text-zinc-600 dark:text-zinc-400',
                  'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900 dark:hover:border-white/40 dark:hover:bg-white/10 dark:hover:text-white'
                )
          )}
        >
          {preset.label}
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CalendarSection
// ─────────────────────────────────────────────────────────────────────────────

interface CalendarSectionProps {
  range: DateRange | undefined;
  onSelect: (range: DateRange | undefined) => void;
  isDesktop: boolean;
}

export function CalendarSection({ range, onSelect, isDesktop }: CalendarSectionProps) {
  const today = startOfDay(new Date());

  return (
    <div
      className={cn(
        'p-6 w-full flex justify-center',
        !isDesktop && 'overflow-x-auto'
      )}
    >
      <CalendarComponent
        mode="range"
        selected={range}
        onSelect={onSelect}
        numberOfMonths={isDesktop ? 2 : 1}
        disabled={(date) => isBefore(date, today)}
        className="p-0"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FooterActions
// ─────────────────────────────────────────────────────────────────────────────

interface FooterActionsProps {
  durationDisplay: string;
  canSave: boolean;
  hasRange: boolean;
  onClear: () => void;
  onSave: () => void;
}

export function FooterActions({ durationDisplay, canSave, hasRange, onClear, onSave }: FooterActionsProps) {
  return (
    <div className={cn(
      'p-4 px-6 flex items-center justify-between',
      'border-t border-zinc-100 dark:border-white/5',
      'bg-zinc-50/50 dark:bg-zinc-950/50'
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
        {hasRange && (
          <button
            type="button"
            onClick={onClear}
            className={cn(
              'px-4 py-2 text-xs font-bold transition-colors',
              'text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
            )}
          >
            Clear
          </button>
        )}
        <button
          type="button"
          onClick={onSave}
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
  );
}
