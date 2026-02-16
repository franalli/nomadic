/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * DestinationSheet
 *
 * Sheet for setting the trip destination.
 * Uses search/autocomplete input with recent destinations.
 */

'use client';

import { MapPin, Search } from 'lucide-react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface DestinationSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value?: string | null;
  onSave: (destination: string) => void;
  recentDestinations?: string[];
}

// Popular destinations for quick selection
const POPULAR_DESTINATIONS = [
  'Paris, France',
  'Tokyo, Japan',
  'New York, USA',
  'London, UK',
  'Dubai, UAE',
  'Barcelona, Spain',
  'Rome, Italy',
  'Bali, Indonesia',
];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function DestinationSheetInner({
  open,
  onOpenChange,
  value,
  onSave,
  recentDestinations = [],
}: DestinationSheetProps) {
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [searchValue, setSearchValue] = useState(value || '');

  // Focus input when opened
  useEffect(() => {
    let focusTimer: ReturnType<typeof setTimeout> | null = null;

    if (open) {
      setSearchValue(value || '');
      // Small delay to ensure the sheet has animated in
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
    toast(`Destination set: ${trimmed}`);
    onOpenChange(false);
  }, [searchValue, onSave, toast, onOpenChange]);

  // Handle quick select
  const handleQuickSelect = useCallback(
    (destination: string) => {
      onSave(destination);
      toast(`Destination set: ${destination}`);
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
      title="Destination"
      hint="Where do you want to go?"
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
            placeholder="Search for a city or country..."
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

        {/* Recent destinations */}
        {recentDestinations.length > 0 && (
          <div>
            <h3 className={DS.text.label + ' mb-3'}>
              Recent
            </h3>
            <div className="flex flex-wrap gap-2">
              {recentDestinations.slice(0, 4).map((dest) => (
                <button
                  key={dest}
                  type="button"
                  onClick={() => handleQuickSelect(dest)}
                  className={cn(
                    'inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-lg',
                    // Tactile Rule: border-2 for visibility, snap-to-black on hover
                    'bg-white border-2 border-zinc-200',
                    'text-xs font-semibold text-zinc-600',
                    'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900 hover:shadow-sm',
                    // Dark: Glass Fill with border-2
                    'dark:bg-white/5 dark:border-2 dark:border-white/15',
                    'dark:text-zinc-400',
                    'dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white',
                    'transition-all duration-150'
                  )}
                >
                  <MapPin className="h-3.5 w-3.5" />
                  {dest}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Popular destinations */}
        <div>
          <h3 className={DS.text.label + ' mb-3'}>
            Popular
          </h3>
          <div className="flex flex-wrap gap-2">
            {POPULAR_DESTINATIONS.map((dest) => (
              <button
                key={dest}
                type="button"
                onClick={() => handleQuickSelect(dest)}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-lg',
                  // Tactile Rule: border-2 for visibility, snap-to-black on hover
                  'bg-white border-2 border-zinc-200',
                  'text-xs font-semibold text-zinc-600',
                  'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900 hover:shadow-sm',
                  // Dark: Glass Fill with border-2
                  'dark:bg-white/5 dark:border-2 dark:border-white/15',
                  'dark:text-zinc-400',
                  'dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white',
                  'transition-all duration-150'
                )}
              >
                <MapPin className="h-3.5 w-3.5" />
                {dest}
              </button>
            ))}
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const DestinationSheet = memo(DestinationSheetInner);

export default DestinationSheet;
