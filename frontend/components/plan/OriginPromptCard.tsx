'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * OriginPromptCard
 *
 * Inline card that prompts user to add a departure city to see flight options.
 * Appears after S2_STRATEGY_READY when origin is not set.
 *
 * @see docs/ux_unified_architecture.md - Origin Prompt Flow
 */


import { Plane } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface OriginPromptCardProps {
  onSetOrigin: (origin: string) => void;
}

export function OriginPromptCard({ onSetOrigin }: OriginPromptCardProps) {
  const [value, setValue] = useState('');

  const handleSubmit = () => {
    if (value.trim()) {
      onSetOrigin(value.trim());
      setValue('');
    }
  };

  return (
    <div
      className={cn(
        'rounded-xl border p-4',
        'bg-zinc-50 border-zinc-200',
        'dark:bg-white/[0.03] dark:border-white/10'
      )}
    >
      <div className="flex items-center gap-3 mb-3">
        <div className="p-2 rounded-lg bg-zinc-100 dark:bg-white/5">
          <Plane className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />
        </div>
        <div className="flex-1">
          <h3 className="font-medium text-sm text-zinc-900 dark:text-white">
            Add departure city to see flights
          </h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            We&apos;ll find the best routes for you
          </p>
        </div>
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="San Francisco"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              handleSubmit();
            }
          }}
          className={cn(
            'flex-1 px-3 py-2 rounded-lg text-sm',
            'bg-zinc-50 dark:bg-black/40',
            'border border-zinc-200 dark:border-white/5',
            'focus:outline-none focus:border-zinc-900 dark:focus:border-emerald-500/50',
            'text-zinc-900 dark:text-white',
            'placeholder:text-zinc-400 dark:placeholder:text-zinc-600'
          )}
        />
        <Button
          onClick={handleSubmit}
          disabled={!value.trim()}
          className={cn(
            'bg-zinc-900 hover:bg-zinc-800 text-white',
            'dark:bg-emerald-600 dark:hover:bg-emerald-500',
            'disabled:opacity-50 disabled:cursor-not-allowed'
          )}
        >
          Add
        </Button>
      </div>
    </div>
  );
}

export default OriginPromptCard;
