/**
 * SystemReceipt
 *
 * Part of the "Command & Receipt" pattern (DS Section 19).
 * Shows a compact system log line below user messages confirming
 * what data was extracted/modified.
 */

'use client';

import { cn } from '@/lib/utils';
import type { AckStatus, AckUpdate, ChatPhase } from '@/types/chat';

// Human-readable labels for known backend keys
const FIELD_LABELS: Record<string, string> = {
  // Core parameters
  destination: 'DESTINATION',
  origin: 'ORIGIN',
  dates: 'DATES',
  budget: 'BUDGET',
  adults: 'TRAVELERS',

  // Booking type toggles
  'booking_types.flights': 'FLIGHTS',
  'booking_types.hotels': 'STAYS',
  'booking_types.activities': 'ACTIVITIES',
  'booking_types.ground_transport': 'TRANSFERS',

  // Flight settings
  'flight_settings.cabin_class': 'CABIN CLASS',
  'flight_settings.direct_only': 'DIRECT FLIGHTS',

  // Hotel settings
  'hotel_settings.min_stars': 'MIN RATING',

  // Activity settings
  'activity_settings.skill_level': 'SKILL LEVEL',
};

/**
 * Format raw field keys to human-readable labels.
 * First checks FIELD_LABELS map, then falls back to cleaning the last segment.
 */
const formatField = (raw: string): string => {
  const normalized = raw.toLowerCase();
  if (FIELD_LABELS[normalized]) return FIELD_LABELS[normalized];

  // Fallback: "flight_settings.cabin_class" -> "CABIN CLASS"
  const lastPart = raw.split('.').pop() || raw;
  return lastPart.replace(/_/g, ' ').toUpperCase();
};

interface SystemReceiptProps {
  ackStatus: AckStatus;
  ackUpdates: AckUpdate[];
  mode?: ChatPhase | 'book';
}

/**
 * Mode-aware verb selection:
 * - SETUP: "EXTRACTED" (broad strokes - destination, dates, budget)
 * - PLAN: "MODIFIED" (surgical edits - specific itinerary nodes)
 * - BOOK: "UPDATED" (transactional - booking selections)
 */
const getModeVerb = (mode?: string): string => {
  switch (mode) {
    case 'setup':
      return 'EXTRACTED';
    case 'plan':
      return 'MODIFIED';
    case 'book':
      return 'UPDATED';
    default:
      return 'UPDATED';
  }
};

export function SystemReceipt({ ackStatus, ackUpdates, mode }: SystemReceiptProps) {
  const isRejected = ackStatus === 'rejected';
  const verb = isRejected ? 'REJECTED' : getModeVerb(mode);
  const fields = ackUpdates.map((u) => formatField(u.field));

  return (
    <div className="mt-2 mr-1 flex items-center gap-2 animate-in fade-in slide-in-from-top-1 duration-300">
      {/* Status Dot - matches DS "Bioluminescent" dark mode aesthetic */}
      {/* Rejection uses Amber (DS Section 20) */}
      <div
        className={cn(
          'w-1 h-1 rounded-full animate-pulse',
          isRejected
            ? 'bg-amber-500' // Rejection: amber (Section 20)
            : ackStatus === 'applied'
              ? 'bg-zinc-400 dark:bg-emerald-500' // Success: emerald glow in dark
              : 'bg-zinc-300 dark:bg-zinc-500' // Partial/other: muted
        )}
      />

      {/* Receipt Text - follows DS Section 17 "System Status Text" pattern */}
      {/* Rejection uses Amber with glow (DS Section 20) */}
      <span
        className={cn(
          // Typography: Technical Monospace with bold for legibility at 10px
          'font-mono text-[10px] uppercase tracking-widest font-bold',
          isRejected
            ? // Rejection: Amber with glow (DS Section 20)
              'text-amber-600 dark:text-amber-500 dark:drop-shadow-[0_0_8px_rgba(245,158,11,0.5)]'
            : // Standard: Zinc/Emerald ("System Pulse")
              'text-zinc-600 dark:text-emerald-500 dark:drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]'
        )}
      >
        &gt;&gt; {verb}: {fields.join(' · ')}
      </span>
    </div>
  );
}

export default SystemReceipt;
