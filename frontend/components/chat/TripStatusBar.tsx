'use client';

/**
 * TripStatusBar - Compact single-line trip summary for mobile.
 *
 * Replaces the two-deck UnifiedChipRow and MobileChatCompactHeader on mobile.
 * Follows the DS "Preference Bar" pattern: always-dark bar with backdrop blur.
 *
 * Visual states:
 *   Empty:    "Where to next?"                           [✏️]
 *   Partial:  "🏝 Bali"  + hint "Add dates..."           [✏️]
 *   Complete: "🏝 Bali · ✈ Rome · 📅 Feb 11–14 · 👤 1"  [✏️]
 */

import { Pencil } from 'lucide-react';
import { memo, useMemo } from 'react';

import { formatDateRangeForPills } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// Specialist emoji map
// ─────────────────────────────────────────────────────────────────────────────

const SPECIALIST_EMOJI: Record<string, string> = {
  diving: '🤿',
  hiking: '🥾',
  skiing: '⛷️',
  cycling: '🚴',
  boating: '⛵',
  surfing: '🏄',
};

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface TripStatusBarProps {
  tripInputs: DocumentTripInputs;
  specialists: string[];
  onEditTap: () => void;
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function TripStatusBarInner({
  tripInputs,
  specialists,
  onEditTap,
  className,
}: TripStatusBarProps) {
  const { destination, origin, start_date, end_date, adults } = tripInputs;
  const hasAnyInput = !!destination;

  // Build summary segments
  const segments = useMemo(() => {
    const parts: string[] = [];
    if (destination) parts.push(`🏝 ${destination}`);
    // Guard: origin may contain "Rome To Bali Feb 11-14" from greedy LLM extraction
    const cleanOrigin = origin?.split(/\s+to\s+/i)[0]?.trim();
    if (cleanOrigin) parts.push(`✈ ${cleanOrigin}`);

    const dateStr = formatDateRangeForPills(start_date, end_date);
    if (dateStr) parts.push(`📅 ${dateStr}`);

    if (adults && adults > 0) parts.push(`👤 ${adults}`);
    return parts;
  }, [destination, origin, start_date, end_date, adults]);

  // Specialist icons (compact glyphs, no labels)
  const specialistIcons = useMemo(() => {
    return specialists
      .filter((s) => s !== 'local_expert')
      .map((s) => SPECIALIST_EMOJI[s])
      .filter(Boolean);
  }, [specialists]);

  return (
    <button
      type="button"
      onClick={onEditTap}
      className={cn(
        'w-full flex items-center gap-2 px-4 py-2.5',
        // DS Preference Bar pattern: always-dark, backdrop blur
        'bg-zinc-900/60 dark:bg-zinc-900/80 backdrop-blur-md',
        'border-b border-white/5',
        'text-left transition-colors',
        'active:bg-zinc-800/80',
        className
      )}
    >
      <div className="flex-1 min-w-0">
        {hasAnyInput ? (
          <p className="text-sm text-zinc-200 truncate">
            {segments.join(' · ')}
            {specialistIcons.length > 0 && (
              <span className="ml-2">{specialistIcons.join(' ')}</span>
            )}
          </p>
        ) : (
          <p className="text-sm text-zinc-500">Where to next?</p>
        )}

        {/* Hint line: only when partial (destination set but no dates) */}
        {destination && !start_date && (
          <p className="text-xs text-zinc-500 mt-0.5">
            Add dates to build itinerary
          </p>
        )}
      </div>

      {/* DS.actions.iconBtn pattern */}
      <Pencil className="w-4 h-4 text-zinc-500 shrink-0" />
    </button>
  );
}

export const TripStatusBar = memo(TripStatusBarInner);
