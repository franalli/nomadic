'use client';

/**
 * TripStatusBar - Compact two-tier trip summary for mobile.
 *
 * Tier 1 (collapsed): Plain text summary — "Bali · Rome · Feb 14-22 · 1 adult"
 * Tier 2 (expanded):  Labeled rows with per-row edit buttons, specialist icons.
 *
 * Tap the bar to toggle between tiers.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, Pencil } from 'lucide-react';
import { memo, useMemo, useState } from 'react';

import { formatDateRangeForPills, formatTravelersForPills } from '@/lib/format-utils';
import { getSpecialistConfig } from '@/lib/specialists';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { SheetType } from '@/types/sheets';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface TripStatusBarProps {
  tripInputs: DocumentTripInputs;
  specialists: string[];
  onOpenSheet: (sheet: SheetType) => void;
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Row helper
// ─────────────────────────────────────────────────────────────────────────────

function Row({
  emoji,
  label,
  onEdit,
}: {
  emoji: string;
  label: string;
  onEdit: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 py-1">
      <span className="text-xs text-white/80 truncate">
        {emoji && <span className="mr-1.5">{emoji}</span>}
        {label}
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onEdit();
        }}
        className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors shrink-0"
      >
        <Pencil className="w-3 h-3" />
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function TripStatusBarInner({
  tripInputs,
  specialists,
  onOpenSheet,
  className,
}: TripStatusBarProps) {
  const { destination, origin, start_date, end_date, adults, children } = tripInputs;
  const hasAnyInput = !!destination;
  const [expanded, setExpanded] = useState(false);

  // Tier 1: plain text summary (no emojis)
  const summaryText = useMemo(() => {
    const parts: string[] = [];
    if (destination) parts.push(destination);
    const cleanOrigin = origin?.split(/\s+to\s+/i)[0]?.trim();
    if (cleanOrigin) parts.push(cleanOrigin);
    const dateStr = formatDateRangeForPills(start_date, end_date);
    if (dateStr) parts.push(dateStr);
    if (adults && adults > 0) parts.push(formatTravelersForPills(adults, children));
    return parts.join(' \u00B7 ');
  }, [destination, origin, start_date, end_date, adults, children]);

  // Trip duration for expanded dates row
  const durationDays = useMemo(() => {
    if (!start_date || !end_date) return null;
    const s = new Date(start_date);
    const e = new Date(end_date);
    const diff = Math.ceil((e.getTime() - s.getTime()) / (1000 * 60 * 60 * 24)) + 1;
    return diff > 0 ? diff : null;
  }, [start_date, end_date]);

  // Specialist display data for expanded row
  const specialistNames = useMemo(() => {
    return specialists
      .filter((s) => s !== 'local_expert')
      .map((s) => {
        const config = getSpecialistConfig(s);
        return config ? { emoji: config.emoji, name: config.displayName } : null;
      })
      .filter(Boolean) as { emoji: string; name: string }[];
  }, [specialists]);

  const cleanOrigin = origin?.split(/\s+to\s+/i)[0]?.trim();

  return (
    <div
      className={cn(
        'w-full',
        'bg-zinc-900 backdrop-blur-md',
        'border-b border-white/10',
        className
      )}
    >
      {/* TIER 1: Always-visible summary line */}
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className={cn(
          'w-full flex items-center gap-2 px-4 py-2',
          'text-left transition-colors',
          'active:bg-zinc-800/80'
        )}
      >
        <div className="flex-1 min-w-0">
          {hasAnyInput ? (
            <p className="text-xs text-white/80 truncate">{summaryText}</p>
          ) : (
            <p className="text-xs text-zinc-500">Where to next?</p>
          )}
        </div>
        <ChevronDown
          className={cn(
            'w-3.5 h-3.5 text-white/50 shrink-0 transition-transform duration-200',
            expanded && 'rotate-180'
          )}
        />
      </button>

      {/* TIER 2: Expanded detail card */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 space-y-0.5">
              {destination && (
                <Row
                  emoji="📍"
                  label={destination}
                  onEdit={() => onOpenSheet('destination')}
                />
              )}
              {cleanOrigin && (
                <Row
                  emoji="✈️"
                  label={`${cleanOrigin} → ${destination || '...'}`}
                  onEdit={() => onOpenSheet('origin')}
                />
              )}
              {start_date && (
                <Row
                  emoji="📅"
                  label={`${formatDateRangeForPills(start_date, end_date) || 'Dates'}${durationDays ? ` (${durationDays} days)` : ''}`}
                  onEdit={() => onOpenSheet('dates')}
                />
              )}
              {adults != null && adults > 0 && (
                <Row
                  emoji="👤"
                  label={formatTravelersForPills(adults, children)}
                  onEdit={() => onOpenSheet('travelers')}
                />
              )}
              {specialistNames.length > 0 && (
                <Row
                  emoji=""
                  label={specialistNames.map((s) => `${s.emoji} ${s.name}`).join('  ')}
                  onEdit={() => onOpenSheet('activities')}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export const TripStatusBar = memo(TripStatusBarInner);
