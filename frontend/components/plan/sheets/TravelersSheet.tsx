/**
 * TravelersSheet
 *
 * Sheet for setting number of travelers.
 * Adults stepper (default 1), Children stepper.
 */

'use client';

import { Minus, Plus, Users } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/utils';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface TravelersSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  adults?: number | null;
  children?: number | null;
  onSave: (adults: number, children: number) => void;
}

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

function Stepper({ label, value, min, max, onChange }: StepperProps) {
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
          className={canIncrement ? buttonEnabled : buttonDisabled}
        >
          <Plus className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
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

  // Format travelers string
  const formatTravelers = useCallback((a: number, c: number): string => {
    const parts: string[] = [];
    if (a === 1) {
      parts.push('1 adult');
    } else {
      parts.push(`${a} adults`);
    }
    if (c > 0) {
      parts.push(`${c} ${c === 1 ? 'child' : 'children'}`);
    }
    return parts.join(', ');
  }, []);

  // Handle save
  const handleSave = useCallback(() => {
    onSave(adults, children);
    toast(`Travelers: ${formatTravelers(adults, children)}`);
    onOpenChange(false);
  }, [adults, children, onSave, toast, formatTravelers, onOpenChange]);

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
        <div className="flex gap-3">
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
              'flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold',
              'transition-all active:scale-[0.98]',
              'bg-zinc-900 text-white shadow-lg shadow-zinc-900/10 hover:bg-zinc-800',
              'dark:bg-emerald-600 dark:hover:bg-emerald-500 dark:shadow-[0_0_20px_-5px_rgba(16,185,129,0.4)]'
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
          <h3 className="text-[10px] font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-3">
            Quick select
          </h3>
          <div className="flex flex-wrap gap-2">
            {[
              { label: 'Solo', adults: 1, children: 0 },
              { label: 'Couple', adults: 2, children: 0 },
              { label: 'Family (2+2)', adults: 2, children: 2 },
              { label: 'Group (4)', adults: 4, children: 0 },
            ].map((preset) => {
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
                      ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
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
        <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
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
        <div className="text-center text-sm text-zinc-500 dark:text-zinc-500">
          {formatTravelers(adults, children)}
        </div>
      </div>
    </BaseSheet>
  );
}

export const TravelersSheet = memo(TravelersSheetInner);

export default TravelersSheet;
