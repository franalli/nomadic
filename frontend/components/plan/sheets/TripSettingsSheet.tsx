/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

/**
 * TripSettingsSheet - Mobile settings relay sheet.
 *
 * A simple BaseSheet containing buttons for each trip input field.
 * Tapping a button closes this sheet and opens the corresponding
 * individual sheet (destination, origin, dates, travelers, budget).
 *
 * This is a two-tap flow for now: pencil → field → editor.
 * Future: collapse into a single stacked form sheet.
 */

import { Calendar, DollarSign, MapPin, Plane, Users } from 'lucide-react';
import { memo, useCallback, useEffect, useRef } from 'react';

import { formatDateRangeForPills } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { SheetType } from '@/types/sheets';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface TripSettingsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tripInputs: DocumentTripInputs;
  onOpenSheet: (sheet: SheetType) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Field Row
// ─────────────────────────────────────────────────────────────────────────────

interface FieldRowProps {
  icon: typeof MapPin;
  label: string;
  value?: string | null;
  onClick: () => void;
}

function FieldRow({ icon: Icon, label, value, onClick }: FieldRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-3 px-4 py-3.5 rounded-xl',
        'transition-all duration-150',
        // DS pills.inactive pattern adapted for list rows
        'bg-white dark:bg-white/5',
        'border-2 border-zinc-200 dark:border-white/15',
        'hover:border-zinc-900 hover:bg-zinc-50',
        'dark:hover:border-white/40 dark:hover:bg-white/10',
        'active:scale-[0.98]'
      )}
    >
      <Icon className={cn(
        'w-5 h-5 shrink-0',
        value ? 'text-zinc-900 dark:text-emerald-400' : 'text-zinc-400 dark:text-zinc-500'
      )} />
      <div className="flex-1 min-w-0 text-left">
        <span className={cn(
          'text-sm font-medium',
          value ? 'text-zinc-900 dark:text-white' : 'text-zinc-400 dark:text-zinc-500'
        )}>
          {value || label}
        </span>
      </div>
      {!value && (
        <span className="text-xs text-zinc-400 dark:text-zinc-600">Tap to set</span>
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function TripSettingsSheetInner({
  open,
  onOpenChange,
  tripInputs,
  onOpenSheet,
}: TripSettingsSheetProps) {
  const { destination, origin, start_date, end_date, adults, children, budget, currency } = tripInputs;

  const mountedRef = useRef(true);
  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  const openField = useCallback(
    (sheet: SheetType) => {
      onOpenChange(false); // Close this sheet first
      // Small delay to let close animation finish before opening next
      setTimeout(() => { if (mountedRef.current) onOpenSheet(sheet); }, 200);
    },
    [onOpenChange, onOpenSheet]
  );

  // Format display values
  const dateStr = formatDateRangeForPills(start_date, end_date);
  const travelerStr = adults
    ? `${adults} adult${adults > 1 ? 's' : ''}${children ? `, ${children} child${children > 1 ? 'ren' : ''}` : ''}`
    : null;
  const budgetStr = budget
    ? new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency || 'USD',
        maximumFractionDigits: 0,
      }).format(budget)
    : null;

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Trip Settings"
      hint="Tap a field to edit"
    >
      <div className="flex flex-col gap-2.5">
        <FieldRow
          icon={MapPin}
          label="Destination"
          value={destination}
          onClick={() => openField('destination')}
        />
        <FieldRow
          icon={Plane}
          label="Origin"
          value={origin}
          onClick={() => openField('origin')}
        />
        <FieldRow
          icon={Calendar}
          label="Dates"
          value={dateStr}
          onClick={() => openField('dates')}
        />
        <FieldRow
          icon={Users}
          label="Travelers"
          value={travelerStr}
          onClick={() => openField('travelers')}
        />
        <FieldRow
          icon={DollarSign}
          label="Budget"
          value={budgetStr}
          onClick={() => openField('budget')}
        />
      </div>
    </BaseSheet>
  );
}

export const TripSettingsSheet = memo(TripSettingsSheetInner);
