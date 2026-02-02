/**
 * OriginPromptCard
 *
 * Inline card that prompts user to add a departure city to see flight options.
 * Appears after S2_STRATEGY_READY when origin is not set.
 *
 * @see docs/ux_unified_architecture.md - Origin Prompt Flow
 */

'use client';

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
        'bg-blue-500/5 border-blue-500/30',
        'dark:bg-blue-500/10 dark:border-blue-500/20'
      )}
    >
      <div className="flex items-center gap-3 mb-3">
        <div className="p-2 rounded-lg bg-blue-500/10 dark:bg-blue-500/20">
          <Plane className="h-4 w-4 text-blue-500 dark:text-blue-400" />
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
            'bg-white dark:bg-zinc-900',
            'border border-zinc-200 dark:border-zinc-700',
            'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500',
            'placeholder:text-zinc-400 dark:placeholder:text-zinc-500'
          )}
        />
        <Button
          onClick={handleSubmit}
          disabled={!value.trim()}
          className={cn(
            'bg-blue-600 hover:bg-blue-500 text-white',
            'dark:bg-blue-600 dark:hover:bg-blue-500',
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
