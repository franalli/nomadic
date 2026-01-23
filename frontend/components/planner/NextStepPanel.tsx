/**
 * NextStepPanel
 *
 * Truthful "Finish setup" checklist for S0/S1 states.
 * Shows exact requirements before plan generation.
 *
 * Rules (updated):
 * - Required: Destination, Start date
 * - Optional: Trip length (required for Stays pricing, itinerary creation)
 * - Defaulted (show as set): Travelers (1 adult)
 * - Optional: Budget (show with "optional" marker)
 * - Conditional: Origin (only show if Flights module ON)
 * - No "Strategy" wording in setup phase
 *
 * IMPORTANT: Reads from document store directly (single source of truth)
 */

'use client';

import { ArrowRight, Check, Loader2, MapPin, Calendar, Users, DollarSign, Plane, Clock } from 'lucide-react';
import { cn, formatDateForDisplay } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import { isBookingEnabled } from '@/types/document';

interface ChecklistItem {
  id: string;
  label: string;
  value?: string | null;
  isRequired: boolean;
  isOptional?: boolean;
  /** Helper text shown when item is not set */
  helperText?: string;
  isSet: boolean;
  icon: typeof MapPin;
  onSet?: () => void;
}

interface NextStepPanelProps {
  // Generation state
  isGenerating?: boolean;
  generatingSubtitle?: string;

  // Actions
  onBuildPlan?: () => void;
  onSetDestination?: () => void;
  onSetOrigin?: () => void;
  onSetDates?: () => void;
  onSetTravelers?: () => void;
  onSetBudget?: () => void;
}

export function NextStepPanel({
  isGenerating = false,
  generatingSubtitle,
  onBuildPlan,
  onSetDestination,
  onSetOrigin,
  onSetDates,
  onSetTravelers,
  onSetBudget,
}: NextStepPanelProps) {
  // Read from document store directly (single source of truth)
  const tripInputs = useDocumentTripInputs();

  // Extract and format values from store
  const destination = tripInputs?.destinations?.[0] ?? null;
  const origin = tripInputs?.origin ?? null;
  const startDate = tripInputs?.start_date ?? null;
  const endDate = tripInputs?.end_date ?? null;
  const tripDuration = tripInputs?.trip_duration ?? null;
  const adults = tripInputs?.adults ?? 1;
  const children = tripInputs?.children ?? 0;
  const budget = tripInputs?.budget ?? null;
  const currency = tripInputs?.currency ?? 'USD';
  const isFlightsEnabled = isBookingEnabled(tripInputs?.booking_types?.flights);

  // Format display values
  const startDateDisplay = startDate ? formatDateForDisplay(startDate) : null;
  const tripLengthDisplay = (() => {
    if (endDate && startDate) {
      const start = new Date(startDate);
      const end = new Date(endDate);
      const nights = Math.round((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24));
      return `${nights} night${nights !== 1 ? 's' : ''}`;
    }
    if (tripDuration) {
      return `${tripDuration} night${tripDuration !== 1 ? 's' : ''}`;
    }
    return null;
  })();

  const travelersDisplay = (() => {
    if (adults === 1 && children === 0) return '1 adult';
    const parts: string[] = [];
    if (adults > 0) parts.push(`${adults} adult${adults !== 1 ? 's' : ''}`);
    if (children > 0) parts.push(`${children} child${children !== 1 ? 'ren' : ''}`);
    return parts.join(', ') || '1 adult';
  })();

  const budgetDisplay = budget != null
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(budget)
    : null;

  // Trip length is always optional for Build plan, but needed for Stays pricing + itinerary
  const hasTripLength = Boolean(endDate || tripDuration);

  // Build checklist items
  const items: ChecklistItem[] = [
    {
      id: 'destination',
      label: 'Destination',
      value: destination,
      isRequired: true,
      isSet: !!destination,
      icon: MapPin,
      onSet: onSetDestination,
    },
    {
      id: 'startDate',
      label: 'Start date',
      value: startDateDisplay,
      isRequired: true,
      isSet: !!startDate,
      icon: Calendar,
      onSet: onSetDates,
    },
    {
      id: 'tripLength',
      label: 'Trip length',
      value: tripLengthDisplay,
      isRequired: false,
      isOptional: true,
      helperText: 'Needed to price stays + build itinerary',
      isSet: hasTripLength,
      icon: Clock,
      onSet: onSetDates,
    },
    {
      id: 'travelers',
      label: 'Travelers',
      value: travelersDisplay,
      isRequired: false,
      isSet: true, // Always considered set (has default)
      icon: Users,
      onSet: onSetTravelers,
    },
    {
      id: 'budget',
      label: 'Budget',
      value: budgetDisplay,
      isRequired: false,
      isOptional: true,
      isSet: !!budget,
      icon: DollarSign,
      onSet: onSetBudget,
    },
  ];

  // Add Origin only if Flights is enabled
  if (isFlightsEnabled) {
    items.splice(1, 0, {
      id: 'origin',
      label: 'Origin',
      value: origin,
      isRequired: true,
      isSet: !!origin,
      icon: Plane,
      onSet: onSetOrigin,
    });
  }

  // Check if can generate plan
  // Required: Destination + Start date
  // Trip length only required if Stays enabled
  const requiredItems = items.filter(item => item.isRequired);
  const missingRequired = requiredItems.filter(item => !item.isSet);
  const canBuildPlan = missingRequired.length === 0;

  // Get helper text for disabled CTA
  const getHelperText = () => {
    if (canBuildPlan) return null;
    const missing = missingRequired.map(item => item.label.toLowerCase());
    if (missing.length === 1) {
      return `Add ${missing[0]} to continue.`;
    }
    return `Add ${missing.slice(0, -1).join(', ')} and ${missing.slice(-1)} to continue.`;
  };

  // S1_GENERATING state - show loader
  if (isGenerating) {
    return (
      <div className="flex flex-col h-full p-6 justify-center items-center">
        <div
          className={cn(
            'w-full max-w-xs mx-auto text-center',
            'px-6 py-7 rounded-2xl',
            'bg-[rgba(255,255,255,0.62)] border border-[rgba(0,0,0,0.06)]',
            'shadow-[0_14px_50px_rgba(0,0,0,0.08)]',
            'dark:bg-[rgba(10,12,12,0.58)] dark:border-[rgba(255,255,255,0.08)]',
            'dark:shadow-[0_18px_60px_rgba(0,0,0,0.45)]',
            'backdrop-blur-[10px]'
          )}
        >
          <Loader2 className="h-8 w-8 animate-spin text-amber-500 mx-auto mb-3" />
          <h2 className="text-lg font-medium text-[var(--theme-text)]">
            Building your plan
          </h2>
          {generatingSubtitle && (
            <p className="text-sm text-[var(--theme-text-muted)] mt-1">
              {generatingSubtitle}
            </p>
          )}
        </div>
      </div>
    );
  }

  // S0_SETUP state - show checklist
  return (
    <div className="flex flex-col h-full p-6 justify-center items-center">
      <div
        className={cn(
          'w-full max-w-xs mx-auto',
          'px-6 py-7 rounded-2xl',
          'bg-[rgba(255,255,255,0.62)] border border-[rgba(0,0,0,0.06)]',
          'shadow-[0_14px_50px_rgba(0,0,0,0.08)]',
          'dark:bg-[rgba(10,12,12,0.58)] dark:border-[rgba(255,255,255,0.08)]',
          'dark:shadow-[0_18px_60px_rgba(0,0,0,0.45)]',
          'backdrop-blur-[10px]'
        )}
      >
        {/* Title */}
        <h2 className="text-lg font-medium text-[var(--theme-text)] text-center">
          Finish setup
        </h2>

        {/* Checklist */}
        <div className="space-y-2 mt-5">
          {items.map((item) => (
            <ChecklistRow
              key={item.id}
              item={item}
            />
          ))}
        </div>

        {/* Build plan CTA */}
        <div className="mt-6">
          <button
            onClick={onBuildPlan}
            disabled={!canBuildPlan}
            className={cn(
              'w-full flex items-center justify-center gap-2',
              'px-4 py-2.5 rounded-lg font-medium text-sm',
              'transition-all duration-200',
              canBuildPlan
                ? 'bg-amber-500 text-white hover:bg-amber-600 active:scale-[0.98]'
                : 'bg-zinc-200 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-600 cursor-not-allowed'
            )}
          >
            Build plan
            <ArrowRight className="h-4 w-4" />
          </button>

          {/* Helper text for disabled state */}
          {!canBuildPlan && (
            <p className="text-xs text-[var(--theme-text-muted)] text-center mt-2">
              {getHelperText()}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function ChecklistRow({ item }: { item: ChecklistItem }) {
  const Icon = item.icon;

  return (
    <div
      className={cn(
        'flex items-center gap-3 px-3 py-2.5 rounded-md transition-all',
        'bg-[rgba(0,0,0,0.02)] border border-[rgba(0,0,0,0.08)]',
        'dark:bg-[rgba(255,255,255,0.03)] dark:border-[rgba(255,255,255,0.08)]',
        !item.isSet && item.onSet && 'cursor-pointer hover:bg-[rgba(0,0,0,0.04)] dark:hover:bg-[rgba(255,255,255,0.05)]'
      )}
      onClick={!item.isSet ? item.onSet : undefined}
    >
      {/* Status indicator */}
      <div className={cn(
        'w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0',
        item.isSet
          ? 'bg-emerald-500/20 text-emerald-500'
          : 'bg-zinc-200/50 text-zinc-400 dark:bg-zinc-700/50 dark:text-zinc-500'
      )}>
        {item.isSet ? (
          <Check className="w-3 h-3" />
        ) : (
          <Icon className="w-3 h-3" />
        )}
      </div>

      {/* Label and value */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={cn(
            'text-sm',
            item.isSet ? 'text-[var(--theme-text)]' : 'text-[var(--theme-text-muted)]'
          )}>
            {item.label}
          </span>
          {item.isOptional && !item.isSet && (
            <span className="text-xs text-zinc-400 dark:text-zinc-600">(optional)</span>
          )}
        </div>
        {item.isSet && item.value && (
          <p className="text-xs text-emerald-600 dark:text-emerald-400 truncate">
            {item.value}
          </p>
        )}
        {/* Helper text for optional items when not set */}
        {!item.isSet && item.helperText && (
          <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-0.5">
            {item.helperText}
          </p>
        )}
      </div>

      {/* Set button for unset items */}
      {!item.isSet && item.onSet && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            item.onSet?.();
          }}
          className="text-xs text-amber-600 dark:text-amber-400 hover:underline flex-shrink-0"
        >
          Set
        </button>
      )}
    </div>
  );
}

export default NextStepPanel;
