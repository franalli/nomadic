'use client';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

export type BudgetType = 'total' | 'per_night' | 'per_person';

export const CURRENCIES = [
  { code: 'USD', symbol: '$', label: 'US Dollar' }, { code: 'EUR', symbol: '€', label: 'Euro' },
  { code: 'GBP', symbol: '£', label: 'British Pound' }, { code: 'JPY', symbol: '¥', label: 'Japanese Yen' },
  { code: 'CAD', symbol: 'C$', label: 'Canadian Dollar' }, { code: 'AUD', symbol: 'A$', label: 'Australian Dollar' },
];

// Quick amount presets
export const AMOUNT_PRESETS = [500, 1000, 2000, 5000, 10000];

// Budget type options
export const BUDGET_TYPES: { value: BudgetType; label: string }[] = [
  { value: 'total', label: 'Total trip' },
  { value: 'per_night', label: 'Per night' },
  { value: 'per_person', label: 'Per person' },
];

// ─────────────────────────────────────────────────────────────────────────────
// CurrencySelector
// ─────────────────────────────────────────────────────────────────────────────

interface CurrencySelectorProps {
  currency: string;
  onChange: (code: string) => void;
}

export function CurrencySelector({ currency, onChange }: CurrencySelectorProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
        Currency
      </h3>
      <div className="flex flex-wrap gap-2">
        {CURRENCIES.map((curr) => {
          const isSelected = currency === curr.code;
          return (
            <button
              key={curr.code}
              type="button"
              onClick={() => onChange(curr.code)}
              className={cn(
                'px-4 py-2.5 rounded-lg text-sm font-medium',
                'transition-all duration-150',
                isSelected
                  // Selected: Solid Black (Light) / Solid White (Dark)
                  ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
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
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AmountInputWithPresets
// ─────────────────────────────────────────────────────────────────────────────

interface AmountInputWithPresetsProps {
  amount: string;
  currencySymbol: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onAmountChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onPreset: (preset: number) => void;
}

export function AmountInputWithPresets({
  amount,
  currencySymbol,
  inputRef,
  onAmountChange,
  onPreset,
}: AmountInputWithPresetsProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
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
          onChange={onAmountChange}
          placeholder="0"
          aria-label="Budget amount"
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
              onClick={() => onPreset(preset)}
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
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BudgetTypeSelector
// ─────────────────────────────────────────────────────────────────────────────

interface BudgetTypeSelectorProps {
  budgetType: BudgetType;
  onChange: (value: BudgetType) => void;
}

export function BudgetTypeSelector({ budgetType, onChange }: BudgetTypeSelectorProps) {
  return (
    <div>
      <h3 className={cn(DS.text.label, 'mb-2')}>
        Budget basis
      </h3>
      <div className="flex gap-2">
        {BUDGET_TYPES.map((type) => {
          const isSelected = budgetType === type.value;
          return (
            <button
              key={type.value}
              type="button"
              onClick={() => onChange(type.value)}
              className={cn(
                'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
                'transition-all duration-150',
                isSelected
                  // Selected: Solid Black (Light) / Solid White (Dark) - maximum contrast per DS.pills.active
                  ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
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
  );
}
