'use client';

/**
 * TravelersSheetParts
 *
 * Extracted sub-components and config for TravelersSheet.
 * - Stepper: reusable +/- stepper control
 * - TRAVELER_PRESETS: quick-select preset config
 * - formatTravelers: human-readable traveler summary
 */

import { Minus, Plus } from 'lucide-react';

import { formatTravelersForPills } from '@/lib/format-utils';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Stepper Component
// ─────────────────────────────────────────────────────────────────────────────

interface StepperProps {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}

export function Stepper({ label, value, min, max, onChange }: StepperProps) {
  const canDecrement = value > min;
  const canIncrement = value < max;

  // Beefier stepper button styles - "Tactile" mechanical buttons
  // Mobile: h-12 (48px) for thumb-friendly touch targets
  const buttonEnabled = cn(
    'w-12 h-12 rounded-full flex items-center justify-center',
    // Light: White with STRONG visible border
    'bg-white border-2 border-zinc-300',
    'text-zinc-700',
    // Dark: Glass Fill - visible substance
    'dark:bg-white/5 dark:border-2 dark:border-white/15',
    'dark:text-zinc-400',
    'transition-all duration-150',
    // Hover: Snap to black (Light) / white (Dark)
    'hover:border-zinc-900 hover:bg-zinc-900 hover:text-white',
    'dark:hover:bg-white dark:hover:border-white dark:hover:text-black',
    'active:scale-95'
  );

  const buttonDisabled = cn(
    'w-12 h-12 rounded-full flex items-center justify-center',
    // Light: Clearly disabled state
    'bg-zinc-50 border-2 border-zinc-200 text-zinc-300',
    // Dark: Dim glass
    'dark:bg-white/[0.02] dark:border-2 dark:border-white/5 dark:text-zinc-700',
    'cursor-not-allowed'
  );

  return (
    <div className="flex items-center justify-between py-4">
      <span className="text-sm font-semibold text-zinc-900 dark:text-white">{label}</span>
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => canDecrement && onChange(value - 1)}
          disabled={!canDecrement}
          aria-label={`Decrease ${label}`}
          className={canDecrement ? buttonEnabled : buttonDisabled}
        >
          <Minus className="h-5 w-5" />
        </button>
        <span className="w-12 text-center text-xl font-bold text-zinc-900 dark:text-white tabular-nums">
          {value}
        </span>
        <button
          type="button"
          onClick={() => canIncrement && onChange(value + 1)}
          disabled={!canIncrement}
          aria-label={`Increase ${label}`}
          className={canIncrement ? buttonEnabled : buttonDisabled}
        >
          <Plus className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Presets config
// ─────────────────────────────────────────────────────────────────────────────

export interface TravelerPreset {
  label: string;
  adults: number;
  children: number;
}

export const TRAVELER_PRESETS: TravelerPreset[] = [
  { label: 'Solo', adults: 1, children: 0 },
  { label: 'Couple', adults: 2, children: 0 },
  { label: 'Family (2+2)', adults: 2, children: 2 },
  { label: 'Group (4)', adults: 4, children: 0 },
];

// ─────────────────────────────────────────────────────────────────────────────
// Formatters
// ─────────────────────────────────────────────────────────────────────────────

/** Format travelers with comma separator (sheet display). Delegates to shared formatter. */
export function formatTravelers(a: number, c: number): string {
  return formatTravelersForPills(a, c, ', ');
}
