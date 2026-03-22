'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * TravelersSheet
 *
 * Sheet for setting number of travelers.
 * Adults stepper (default 1), Children stepper.
 */


import { Users } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import { BaseSheet } from './BaseSheet';
import { formatTravelers, Stepper, TRAVELER_PRESETS } from './TravelersSheetParts';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface TravelersSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  adults?: number | null;
  children?: number | null;
  onSave: (adults: number, children: number) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function TravelersSheetInner({
  open,
  onOpenChange,
  adults: initialAdults,
  children: initialChildren,
  onSave,
}: TravelersSheetProps) {
  const { toast } = useToast();
  const [adults, setAdults] = useState(initialAdults ?? 1);
  const [children, setChildren] = useState(initialChildren ?? 0);

  // Reset when opened
  useEffect(() => {
    if (open) {
      setAdults(initialAdults ?? 1);
      setChildren(initialChildren ?? 0);
    }
  }, [open, initialAdults, initialChildren]);

  // Handle save
  const handleSave = useCallback(() => {
    onSave(adults, children);
    toast(`Travelers: ${formatTravelers(adults, children)}`);
    onOpenChange(false);
  }, [adults, children, onSave, toast, onOpenChange]);

  // Quick presets
  const handlePreset = useCallback((a: number, c: number) => {
    setAdults(a);
    setChildren(c);
  }, []);

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Travelers"
      hint="How many people are traveling?"
      footer={
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className={cn(
              'flex-1 px-4 py-2.5 rounded-xl text-sm font-medium',
              'text-zinc-500 dark:text-zinc-500',
              'hover:text-zinc-900 hover:bg-zinc-100',
              'dark:hover:text-white dark:hover:bg-white/5',
              'transition-colors'
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            className={cn(
              DS.actions.primary,
              'flex-1 px-4 py-2.5 font-semibold'
            )}
          >
            Save
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Quick presets */}
        <div>
          <h3 className={cn(DS.text.label, 'mb-2')}>
            Quick select
          </h3>
          <div className="flex flex-wrap gap-2">
            {TRAVELER_PRESETS.map((preset) => {
              const isSelected = adults === preset.adults && children === preset.children;
              return (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => handlePreset(preset.adults, preset.children)}
                  className={cn(
                    'px-4 py-2.5 rounded-lg text-sm font-medium',
                    'transition-all duration-150',
                    isSelected
                      // Selected: Solid Black / White (maximum contrast)
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
                  <Users className="inline h-3.5 w-3.5 mr-1.5" />
                  {preset.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Steppers */}
        <div className="divide-y divide-zinc-200 dark:divide-white/10">
          <Stepper
            label="Adults"
            value={adults}
            min={1}
            max={20}
            onChange={setAdults}
          />
          <Stepper
            label="Children"
            value={children}
            min={0}
            max={20}
            onChange={setChildren}
          />
        </div>

        {/* Summary */}
        <div className="text-center text-sm text-zinc-600 dark:text-zinc-400">
          {formatTravelers(adults, children)}
        </div>
      </div>
    </BaseSheet>
  );
}

export const TravelersSheet = memo(TravelersSheetInner);

export default TravelersSheet;
