/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { Minus, Plus } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';

export interface StepperProps {
  value: number;
  min?: number; // default 0
  max?: number; // default 10
  onChange: (value: number) => void;
  disabled?: boolean;
  size?: 'sm' | 'default';
  label?: string; // for aria-label
}

export const Stepper = React.forwardRef<HTMLDivElement, StepperProps>(
  ({ value, min = 0, max = 10, onChange, disabled = false, size = 'default', label }, ref) => {
    const canDecrease = value > min && !disabled;
    const canIncrease = value < max && !disabled;

    const handleDecrease = () => {
      if (canDecrease) {
        onChange(value - 1);
      }
    };

    const handleIncrease = () => {
      if (canIncrease) {
        onChange(value + 1);
      }
    };

    const buttonSize = size === 'sm' ? 'w-8 h-8' : 'w-10 h-10';
    const valueSize = size === 'sm' ? 'text-sm' : 'text-lg';
    const valueWidth = size === 'sm' ? 'w-8' : 'w-10';

    return (
      <div ref={ref} className="flex items-center justify-center gap-2">
        {/* Decrease button */}
        <button
          type="button"
          onClick={handleDecrease}
          disabled={!canDecrease}
          aria-label={label ? `Decrease ${label}` : 'Decrease'}
          className={cn(
            buttonSize,
            'rounded-full flex items-center justify-center',
            'transition-all duration-150 active:scale-95',
            canDecrease
              ? cn(
                  'bg-white dark:bg-white/5',
                  'border-2 border-zinc-300 dark:border-white/15',
                  'text-zinc-700 dark:text-zinc-400',
                  'hover:border-zinc-900 hover:bg-zinc-900 hover:text-white',
                  'dark:hover:bg-white dark:hover:border-white dark:hover:text-black'
                )
              : cn(
                  'bg-zinc-50 dark:bg-white/[0.02]',
                  'border-2 border-zinc-200 dark:border-white/5',
                  'text-zinc-300 dark:text-zinc-700',
                  'cursor-not-allowed'
                )
          )}
        >
          <Minus className="w-4 h-4" />
        </button>

        {/* Value display */}
        <div className={cn(valueWidth, valueSize, 'text-center font-bold text-zinc-900 dark:text-white')}>
          {value}
        </div>

        {/* Increase button */}
        <button
          type="button"
          onClick={handleIncrease}
          disabled={!canIncrease}
          aria-label={label ? `Increase ${label}` : 'Increase'}
          className={cn(
            buttonSize,
            'rounded-full flex items-center justify-center',
            'transition-all duration-150 active:scale-95',
            canIncrease
              ? cn(
                  'bg-white dark:bg-white/5',
                  'border-2 border-zinc-300 dark:border-white/15',
                  'text-zinc-700 dark:text-zinc-400',
                  'hover:border-zinc-900 hover:bg-zinc-900 hover:text-white',
                  'dark:hover:bg-white dark:hover:border-white dark:hover:text-black'
                )
              : cn(
                  'bg-zinc-50 dark:bg-white/[0.02]',
                  'border-2 border-zinc-200 dark:border-white/5',
                  'text-zinc-300 dark:text-zinc-700',
                  'cursor-not-allowed'
                )
          )}
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
    );
  }
);

Stepper.displayName = 'Stepper';
