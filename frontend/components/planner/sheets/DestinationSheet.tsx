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
    if (open) {
      setSearchValue(value || '');
      // Small delay to ensure the sheet has animated in
      setTimeout(() => inputRef.current?.focus(), 100);
    }
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
      <div className="space-y-4">
        {/* Search input */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--theme-text-muted)]" />
          <input
            ref={inputRef}
            type="text"
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search for a city or country..."
            className={cn(
              'w-full pl-10 pr-4 py-3 rounded-lg',
              'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
              'text-[var(--theme-text)] placeholder:text-[var(--theme-text-muted)]',
              'focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50',
              'transition-colors'
            )}
          />
        </div>

        {/* Recent destinations */}
        {recentDestinations.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Recent
            </h3>
            <div className="flex flex-wrap gap-2">
              {recentDestinations.slice(0, 4).map((dest) => (
                <button
                  key={dest}
                  type="button"
                  onClick={() => handleQuickSelect(dest)}
                  className={cn(
                    'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                    'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                    'text-sm text-[var(--theme-text)]',
                    'hover:border-amber-500/50 hover:bg-amber-500/10',
                    'transition-colors'
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
          <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
            Popular
          </h3>
          <div className="flex flex-wrap gap-2">
            {POPULAR_DESTINATIONS.map((dest) => (
              <button
                key={dest}
                type="button"
                onClick={() => handleQuickSelect(dest)}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                  'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                  'text-sm text-[var(--theme-text)]',
                  'hover:border-amber-500/50 hover:bg-amber-500/10',
                  'transition-colors'
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
