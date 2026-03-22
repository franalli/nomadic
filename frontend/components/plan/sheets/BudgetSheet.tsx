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
import {
  AmountInputWithPresets,
  type BudgetType,
  BudgetTypeSelector,
  CURRENCIES,
  CurrencySelector,
} from './BudgetSheetParts';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type { BudgetType } from './BudgetSheetParts';

interface BudgetSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  amount?: number | null;
  currency?: string;
  budgetType?: BudgetType;
  onSave: (amount: number, currency: string, budgetType: BudgetType) => void;
}

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
        <CurrencySelector currency={currency} onChange={setCurrency} />

        {/* Amount input - THE BIG NUMBER */}
        <AmountInputWithPresets
          amount={amount}
          currencySymbol={currencySymbol}
          inputRef={inputRef}
          onAmountChange={handleInputChange}
          onPreset={handlePreset}
        />

        {/* Budget type selector */}
        <BudgetTypeSelector budgetType={budgetType} onChange={setBudgetType} />
      </div>
    </BaseSheet>
  );
}

export const BudgetSheet = memo(BudgetSheetInner);

export default BudgetSheet;
