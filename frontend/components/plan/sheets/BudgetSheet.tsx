'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * BudgetSheet
 *
 * Sheet for setting trip budget.
 * Currency + amount, budget type selector (total/per-night/per-person).
 */


import { memo, useCallback, useEffect, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type BudgetType = 'total' | 'per_night' | 'per_person';

interface BudgetSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  amount?: number | null;
  currency?: string;
  budgetType?: BudgetType;
  onSave: (amount: number, currency: string, budgetType: BudgetType) => void;
}

// Currency options
const CURRENCIES = [
  { code: 'USD', symbol: '$', label: 'US Dollar' },
  { code: 'EUR', symbol: '€', label: 'Euro' },
  { code: 'GBP', symbol: '£', label: 'British Pound' },
  { code: 'JPY', symbol: '¥', label: 'Japanese Yen' },
  { code: 'CAD', symbol: 'C$', label: 'Canadian Dollar' },
  { code: 'AUD', symbol: 'A$', label: 'Australian Dollar' },
];

// Budget type options
const BUDGET_TYPES: { value: BudgetType; label: string }[] = [
  { value: 'total', label: 'Total trip' },
  { value: 'per_night', label: 'Per night' },
  { value: 'per_person', label: 'Per person' },
];

// Quick amount presets
const AMOUNT_PRESETS = [500, 1000, 2000, 5000, 10000];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function BudgetSheetInner({
  open,
  onOpenChange,
  amount: initialAmount,
  currency: initialCurrency = 'USD',
  budgetType: initialBudgetType = 'total',
  onSave,
}: BudgetSheetProps) {
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [amount, setAmount] = useState<string>(initialAmount?.toString() || '');
  const [currency, setCurrency] = useState(initialCurrency);
  const [budgetType, setBudgetType] = useState<BudgetType>(initialBudgetType);

  // Reset when opened
  useEffect(() => {
    let focusTimer: ReturnType<typeof setTimeout> | null = null;

    if (open) {
      setAmount(initialAmount?.toString() || '');
      setCurrency(initialCurrency);
      setBudgetType(initialBudgetType);
      focusTimer = setTimeout(() => inputRef.current?.focus(), 100);
    }

    return () => {
      if (focusTimer) {
        clearTimeout(focusTimer);
      }
    };
  }, [open, initialAmount, initialCurrency, initialBudgetType]);

  // Get currency symbol
  const currencySymbol = CURRENCIES.find((c) => c.code === currency)?.symbol || '$';

  // Format budget for display
  const formatBudget = useCallback(
    (amt: number, curr: string, type: BudgetType): string => {
      const sym = CURRENCIES.find((c) => c.code === curr)?.symbol || '$';
      const formatted = amt >= 1000 ? `${sym}${(amt / 1000).toFixed(amt % 1000 === 0 ? 0 : 1)}k` : `${sym}${amt}`;
      switch (type) {
        case 'per_night':
          return `${formatted}/night`;
        case 'per_person':
          return `${formatted}/person`;
        default:
          return formatted;
      }
    },
    []
  );

  // Handle save
  const handleSave = useCallback(() => {
    const numAmount = parseInt(amount, 10);
    if (isNaN(numAmount) || numAmount <= 0) return;

    onSave(numAmount, currency, budgetType);
    toast(`Budget set: ${formatBudget(numAmount, currency, budgetType)}`);
    onOpenChange(false);
  }, [amount, currency, budgetType, onSave, toast, formatBudget, onOpenChange]);

  // Handle preset click
  const handlePreset = useCallback((preset: number) => {
    setAmount(preset.toString());
  }, []);

  // Handle input change (numbers only)
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value.replace(/[^0-9]/g, '');
    setAmount(value);
  }, []);

  const canSave = amount.length > 0 && parseInt(amount, 10) > 0;

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Budget"
      hint="Set your trip budget (optional)"
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
            disabled={!canSave}
            className={cn(
              canSave ? DS.actions.primary : DS.actions.primaryDisabled,
              'flex-1 px-4 py-2.5 font-semibold'
            )}
          >
            Save
          </button>
        </div>
      }
    >
      <div className="space-y-6">
        {/* Currency selector */}
        <div>
          <h3 className={cn(DS.text.label, 'mb-3')}>
            Currency
          </h3>
          <div className="flex flex-wrap gap-2">
            {CURRENCIES.map((curr) => {
              const isSelected = currency === curr.code;
              return (
                <button
                  key={curr.code}
                  type="button"
                  onClick={() => setCurrency(curr.code)}
                  className={cn(
                    'px-4 py-2.5 rounded-lg text-sm font-medium',
                    'transition-all duration-150',
                    isSelected
                      // Selected: Solid Black (Light) / Solid White (Dark)
                      ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                      // Inactive: Glass Fill (Dark) - substance, not just outline
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                  )}
                >
                  {curr.symbol} {curr.code}
                </button>
              );
            })}
          </div>
        </div>

        {/* Amount input - THE BIG NUMBER */}
        <div>
          <h3 className={cn(DS.text.label, 'mb-3')}>
            Amount
          </h3>
          <div className="relative flex justify-center py-8">
            <span className="text-3xl text-zinc-400 dark:text-zinc-600 font-bold absolute left-6 top-1/2 -translate-y-1/2">
              {currencySymbol}
            </span>
            <input
              ref={inputRef}
              type="text"
              inputMode="numeric"
              value={amount}
              onChange={handleInputChange}
              placeholder="0"
              className={cn(
                'bg-transparent',
                // HUGE and BOLD - this determines the luxury level
                'text-5xl font-bold text-center tracking-tight',
                'text-zinc-900 dark:text-white',
                'border-none focus:ring-0 w-full',
                'placeholder:text-zinc-300 dark:placeholder:text-zinc-700',
                'focus:outline-none',
                // Matrix caret effect
                'caret-zinc-900 dark:caret-emerald-500'
              )}
            />
          </div>

          {/* Quick presets */}
          <div className="flex flex-wrap justify-center gap-2 mt-2">
            {AMOUNT_PRESETS.map((preset) => {
              const isSelected = amount === preset.toString();
              return (
                <button
                  key={preset}
                  type="button"
                  onClick={() => handlePreset(preset)}
                  className={cn(
                    'px-3.5 py-1.5 rounded-full text-xs font-semibold',
                    'transition-all duration-150',
                    isSelected
                      // Selected: Solid Black / White
                      ? 'bg-zinc-900 text-white border-2 border-transparent shadow-md dark:bg-white dark:text-black dark:border-transparent'
                      // Inactive: Glass Fill
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-500',
                          'hover:border-zinc-900 hover:text-zinc-900',
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                  )}
                >
                  {currencySymbol}{preset >= 1000 ? `${preset / 1000}k` : preset}
                </button>
              );
            })}
          </div>
        </div>

        {/* Budget type selector */}
        <div>
          <h3 className={cn(DS.text.label, 'mb-3')}>
            Budget basis
          </h3>
          <div className="flex gap-2">
            {BUDGET_TYPES.map((type) => {
              const isSelected = budgetType === type.value;
              return (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setBudgetType(type.value)}
                  className={cn(
                    'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
                    'transition-all duration-150',
                    isSelected
                      // Selected: Solid Black (Light) / Solid White (Dark) - maximum contrast per DS.pills.active
                      ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                      // Inactive: Glass Fill - Tactile Rule
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                  )}
                >
                  {type.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const BudgetSheet = memo(BudgetSheetInner);

export default BudgetSheet;
