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

  return (
    <div className="flex items-center justify-between py-3">
      <span className="text-sm font-medium text-[var(--theme-text)]">{label}</span>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => canDecrement && onChange(value - 1)}
          disabled={!canDecrement}
          className={cn(
            'w-8 h-8 rounded-full flex items-center justify-center',
            'border transition-colors',
            canDecrement
              ? 'border-[var(--theme-border)] text-[var(--theme-text)] hover:bg-[var(--theme-overlay)]'
              : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] opacity-40 cursor-not-allowed'
          )}
        >
          <Minus className="h-4 w-4" />
        </button>
        <span className="w-8 text-center text-lg font-semibold text-[var(--theme-text)]">
          {value}
        </span>
        <button
          type="button"
          onClick={() => canIncrement && onChange(value + 1)}
          disabled={!canIncrement}
          className={cn(
            'w-8 h-8 rounded-full flex items-center justify-center',
            'border transition-colors',
            canIncrement
              ? 'border-[var(--theme-border)] text-[var(--theme-text)] hover:bg-[var(--theme-overlay)]'
              : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] opacity-40 cursor-not-allowed'
          )}
        >
          <Plus className="h-4 w-4" />
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
              'flex-1 px-4 py-2.5 rounded-lg text-sm font-medium',
              'border border-[var(--theme-border)]',
              'text-[var(--theme-text-muted)]',
              'hover:bg-[var(--theme-overlay)]',
              'transition-colors'
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            className={cn(
              'flex-1 px-4 py-2.5 rounded-lg text-sm font-medium',
              'bg-amber-500 text-white hover:bg-amber-600',
              'transition-colors'
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
          <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
            Quick select
          </h3>
          <div className="flex flex-wrap gap-2">
            {[
              { label: 'Solo', adults: 1, children: 0 },
              { label: 'Couple', adults: 2, children: 0 },
              { label: 'Family (2+2)', adults: 2, children: 2 },
              { label: 'Group (4)', adults: 4, children: 0 },
            ].map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => handlePreset(preset.adults, preset.children)}
                className={cn(
                  'px-3 py-1.5 rounded-full text-sm',
                  'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                  'text-[var(--theme-text)]',
                  'hover:border-amber-500/50 hover:bg-amber-500/10',
                  'transition-colors',
                  adults === preset.adults && children === preset.children &&
                    'border-amber-500 bg-amber-500/10'
                )}
              >
                <Users className="inline h-3.5 w-3.5 mr-1.5" />
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        {/* Steppers */}
        <div className="divide-y divide-[var(--theme-border)]">
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
        <div className="text-center text-sm text-[var(--theme-text-muted)]">
          {formatTravelers(adults, children)}
        </div>
      </div>
    </BaseSheet>
  );
}

export const TravelersSheet = memo(TravelersSheetInner);

export default TravelersSheet;
