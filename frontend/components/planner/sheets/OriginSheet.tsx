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
    if (open) {
      setSearchValue(value || '');
      setTimeout(() => inputRef.current?.focus(), 100);
    }
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
            placeholder="Search for a city or airport..."
            className={cn(
              'w-full pl-10 pr-4 py-3 rounded-lg',
              'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
              'text-[var(--theme-text)] placeholder:text-[var(--theme-text-muted)]',
              'focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50',
              'transition-colors'
            )}
          />
        </div>

        {/* Recent origins */}
        {recentOrigins.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Recent
            </h3>
            <div className="flex flex-wrap gap-2">
              {recentOrigins.slice(0, 4).map((origin) => (
                <button
                  key={origin}
                  type="button"
                  onClick={() => handleQuickSelect(origin)}
                  className={cn(
                    'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                    'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                    'text-sm text-[var(--theme-text)]',
                    'hover:border-amber-500/50 hover:bg-amber-500/10',
                    'transition-colors'
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
          <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
            Major hubs
          </h3>
          <div className="flex flex-wrap gap-2">
            {POPULAR_ORIGINS.map((origin) => (
              <button
                key={origin}
                type="button"
                onClick={() => handleQuickSelect(origin)}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                  'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                  'text-sm text-[var(--theme-text)]',
                  'hover:border-amber-500/50 hover:bg-amber-500/10',
                  'transition-colors'
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
