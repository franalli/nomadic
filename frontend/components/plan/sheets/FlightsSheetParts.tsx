'use client';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { FlightSettings } from '@/types/document';

// Cabin class options
export const CABIN_OPTIONS: { value: FlightSettings['cabin_class']; label: string }[] = [
  { value: 'economy', label: 'Economy' },
  { value: 'premium_economy', label: 'Premium' },
  { value: 'business', label: 'Business' },
  { value: 'first', label: 'First' },
];

// Stops options
export const STOPS_OPTIONS = [
  { value: 'any', label: 'Any stops', directOnly: false },
  { value: 'nonstop', label: 'Nonstop only', directOnly: true },
];

// ─────────────────────────────────────────────────────────────────────────────
// TripTypeSelector
// ─────────────────────────────────────────────────────────────────────────────

interface TripTypeSelectorProps {
  roundTrip: boolean;
  onChange: (roundTrip: boolean) => void;
}

export function TripTypeSelector({ roundTrip, onChange }: TripTypeSelectorProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
        Trip type
      </h3>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onChange(true)}
          className={cn(
            'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
            'transition-all duration-150',
            roundTrip
              // Selected: Solid Black (maximum contrast)
              ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
              // Tactile: Crisp border, snap-to-black hover
              // Inactive: Glass Fill - visible buttons
                : cn(
                    'bg-white border-2 border-zinc-200 text-zinc-600',
                    'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                    // Dark: Glass substance
                    'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                    'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                  )
          )}
        >
          Round trip
        </button>
        <button
          type="button"
          onClick={() => onChange(false)}
          className={cn(
            'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
            'transition-all duration-150',
            !roundTrip
              ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
              // Inactive: Glass Fill - visible buttons
                : cn(
                    'bg-white border-2 border-zinc-200 text-zinc-600',
                    'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                    // Dark: Glass substance
                    'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                    'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                  )
          )}
        >
          One-way
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CabinClassSelector
// ─────────────────────────────────────────────────────────────────────────────

interface CabinClassSelectorProps {
  cabinClass: FlightSettings['cabin_class'];
  onChange: (value: FlightSettings['cabin_class']) => void;
}

export function CabinClassSelector({ cabinClass, onChange }: CabinClassSelectorProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
        Cabin class
      </h3>
      <div className="flex flex-wrap gap-2">
        {CABIN_OPTIONS.map((option) => {
          const isSelected = cabinClass === option.value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className={cn(
                'px-4 py-2.5 rounded-lg text-sm font-medium',
                'transition-all duration-150',
                isSelected
                  // Selected: Solid Black (maximum contrast)
                  ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
                  // Tactile: Crisp border, snap-to-black hover
                  // Inactive: Glass Fill - visible buttons
                : cn(
                    'bg-white border-2 border-zinc-200 text-zinc-600',
                    'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                    // Dark: Glass substance
                    'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                    'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                  )
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// StopsSelector
// ─────────────────────────────────────────────────────────────────────────────

interface StopsSelectorProps {
  directOnly: boolean;
  onChange: (directOnly: boolean) => void;
}

export function StopsSelector({ directOnly, onChange }: StopsSelectorProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
        Stops
      </h3>
      <div className="flex gap-2">
        {STOPS_OPTIONS.map((option) => {
          const isSelected = directOnly === option.directOnly;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.directOnly)}
              className={cn(
                'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
                'transition-all duration-150',
                isSelected
                  // Selected: Solid Black (maximum contrast)
                  ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
                  // Tactile: Crisp border, snap-to-black hover
                  // Inactive: Glass Fill - visible buttons
                : cn(
                    'bg-white border-2 border-zinc-200 text-zinc-600',
                    'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                    // Dark: Glass substance
                    'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                    'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                  )
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
