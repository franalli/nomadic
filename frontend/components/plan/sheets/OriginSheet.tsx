/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * OriginSheet
 *
 * Sheet for setting the departure location (origin).
 * Similar to DestinationSheet but for origin.
 */

'use client';

import { Plane, Search } from 'lucide-react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/utils';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface OriginSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value?: string | null;
  onSave: (origin: string) => void;
  recentOrigins?: string[];
}

// Popular origins (major hubs)
const POPULAR_ORIGINS = [
  'New York (JFK)',
  'Los Angeles (LAX)',
  'London (LHR)',
  'Chicago (ORD)',
  'San Francisco (SFO)',
  'Miami (MIA)',
  'Boston (BOS)',
  'Seattle (SEA)',
];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function OriginSheetInner({
  open,
  onOpenChange,
  value,
  onSave,
  recentOrigins = [],
}: OriginSheetProps) {
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [searchValue, setSearchValue] = useState(value || '');

  // Focus input when opened
  useEffect(() => {
    let focusTimer: ReturnType<typeof setTimeout> | null = null;

    if (open) {
      setSearchValue(value || '');
      focusTimer = setTimeout(() => inputRef.current?.focus(), 100);
    }

    return () => {
      if (focusTimer) {
        clearTimeout(focusTimer);
      }
    };
  }, [open, value]);

  // Handle save
  const handleSave = useCallback(() => {
    const trimmed = searchValue.trim();
    if (!trimmed) return;

    onSave(trimmed);
    toast(`Origin set: ${trimmed}`);
    onOpenChange(false);
  }, [searchValue, onSave, toast, onOpenChange]);

  // Handle quick select
  const handleQuickSelect = useCallback(
    (origin: string) => {
      onSave(origin);
      toast(`Origin set: ${origin}`);
      onOpenChange(false);
    },
    [onSave, toast, onOpenChange]
  );

  // Handle enter key
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && searchValue.trim()) {
        handleSave();
      }
    },
    [handleSave, searchValue]
  );

  const canSave = searchValue.trim().length > 0;

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Origin"
      hint="Where are you departing from?"
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
              'flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold',
              'transition-all active:scale-[0.98]',
              canSave
                ? 'bg-zinc-900 text-white shadow-lg shadow-zinc-900/10 hover:bg-zinc-800 dark:bg-emerald-600 dark:hover:bg-emerald-500 dark:shadow-[0_0_20px_-5px_rgba(16,185,129,0.4)]'
                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600 cursor-not-allowed'
            )}
          >
            Save
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Search input */}
        <div className="relative group">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-zinc-400 dark:text-zinc-500 group-focus-within:text-zinc-900 dark:group-focus-within:text-white transition-colors" />
          <input
            ref={inputRef}
            type="text"
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search for a city or airport..."
            className={cn(
              'w-full h-14 pl-12 pr-4 rounded-xl',
              // Light: Hollow grey field
              'bg-zinc-50 border border-zinc-200',
              'focus:border-zinc-900 focus:bg-white',
              // Dark: THE VOID - darker than the card, no border until focus
              'dark:bg-black/50 dark:border-transparent',
              'dark:focus:border-emerald-500/50 dark:focus:bg-black/60',
              // Text
              'text-zinc-900 dark:text-white text-base font-medium',
              'placeholder:text-zinc-400 dark:placeholder:text-zinc-600',
              // Focus effects
              'focus:outline-none focus:ring-0',
              'focus:shadow-lg focus:shadow-zinc-200/50 dark:focus:shadow-[0_0_20px_-5px_rgba(16,185,129,0.15)]',
              'transition-all duration-200'
            )}
          />
        </div>

        {/* Recent origins */}
        {recentOrigins.length > 0 && (
          <div>
            <h3 className="text-[10px] font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-3">
              Recent
            </h3>
            <div className="flex flex-wrap gap-2">
              {recentOrigins.slice(0, 4).map((origin) => (
                <button
                  key={origin}
                  type="button"
                  onClick={() => handleQuickSelect(origin)}
                  className={cn(
                    'inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-lg',
                    // Light: White card with border
                    'bg-white border-2 border-zinc-200',
                    'text-xs font-semibold text-zinc-600',
                    'hover:border-zinc-900 hover:text-zinc-900 hover:shadow-sm',
                    // Dark: Glass Fill - substance, not just outline
                    'dark:bg-white/5 dark:border-2 dark:border-white/15',
                    'dark:text-zinc-400',
                    'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40',
                    'transition-all duration-150'
                  )}
                >
                  <Plane className="h-3.5 w-3.5" />
                  {origin}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Popular origins */}
        <div>
          <h3 className="text-[10px] font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-3">
            Major hubs
          </h3>
          <div className="flex flex-wrap gap-2">
            {POPULAR_ORIGINS.map((origin) => (
              <button
                key={origin}
                type="button"
                onClick={() => handleQuickSelect(origin)}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-lg',
                  // Light: White card with border
                  'bg-white border-2 border-zinc-200',
                  'text-xs font-semibold text-zinc-600',
                  'hover:border-zinc-900 hover:text-zinc-900 hover:shadow-sm',
                  // Dark: Glass Fill - substance, not just outline
                  'dark:bg-white/5 dark:border-2 dark:border-white/15',
                  'dark:text-zinc-400',
                  'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40',
                  'transition-all duration-150'
                )}
              >
                <Plane className="h-3.5 w-3.5" />
                {origin}
              </button>
            ))}
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const OriginSheet = memo(OriginSheetInner);

export default OriginSheet;
