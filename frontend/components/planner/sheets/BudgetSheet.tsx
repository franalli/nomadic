/**
 * BudgetSheet
 *
 * Sheet for setting trip budget.
 * Currency + amount, budget type selector (total/per-night/per-person).
 */

'use client';

import { memo, useCallback, useEffect, useRef, useState } from 'react';

import { BaseSheet } from './BaseSheet';
import { cn } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type BudgetType = 'total' | 'per_night' | 'per_person';

export interface BudgetSheetProps {
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
    if (open) {
      setAmount(initialAmount?.toString() || '');
      setCurrency(initialCurrency);
      setBudgetType(initialBudgetType);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
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
            disabled={!canSave}
            className={cn(
              'flex-1 px-4 py-2.5 rounded-lg text-sm font-medium',
              'transition-colors',
              canSave
                ? 'bg-amber-500 text-white hover:bg-amber-600'
                : 'bg-zinc-200 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-600 cursor-not-allowed'
            )}
          >
            Save
          </button>
        </div>
      }
    >
      <div className="space-y-5">
        {/* Currency selector */}
        <div>
          <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
            Currency
          </h3>
          <div className="flex flex-wrap gap-2">
            {CURRENCIES.map((curr) => (
              <button
                key={curr.code}
                type="button"
                onClick={() => setCurrency(curr.code)}
                className={cn(
                  'px-3 py-1.5 rounded-full text-sm',
                  'border transition-colors',
                  currency === curr.code
                    ? 'border-amber-500 bg-amber-500/10 text-amber-600 dark:text-amber-400'
                    : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-amber-500/50'
                )}
              >
                {curr.symbol} {curr.code}
              </button>
            ))}
          </div>
        </div>

        {/* Amount input */}
        <div>
          <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
            Amount
          </h3>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-lg text-[var(--theme-text-muted)]">
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
                'w-full pl-10 pr-4 py-3 rounded-lg text-lg font-semibold',
                'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                'text-[var(--theme-text)] placeholder:text-[var(--theme-text-muted)]',
                'focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50',
                'transition-colors'
              )}
            />
          </div>

          {/* Quick presets */}
          <div className="flex flex-wrap gap-2 mt-3">
            {AMOUNT_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => handlePreset(preset)}
                className={cn(
                  'px-3 py-1.5 rounded-full text-sm',
                  'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                  'text-[var(--theme-text)]',
                  'hover:border-amber-500/50 hover:bg-amber-500/10',
                  'transition-colors',
                  amount === preset.toString() && 'border-amber-500 bg-amber-500/10'
                )}
              >
                {currencySymbol}{preset >= 1000 ? `${preset / 1000}k` : preset}
              </button>
            ))}
          </div>
        </div>

        {/* Budget type selector */}
        <div>
          <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
            Budget basis
          </h3>
          <div className="flex gap-2">
            {BUDGET_TYPES.map((type) => (
              <button
                key={type.value}
                type="button"
                onClick={() => setBudgetType(type.value)}
                className={cn(
                  'flex-1 px-3 py-2 rounded-lg text-sm',
                  'border transition-colors',
                  budgetType === type.value
                    ? 'border-amber-500 bg-amber-500/10 text-amber-600 dark:text-amber-400'
                    : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-amber-500/50'
                )}
              >
                {type.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const BudgetSheet = memo(BudgetSheetInner);

export default BudgetSheet;
