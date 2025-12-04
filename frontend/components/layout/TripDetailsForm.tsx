'use client';

import {
  AlertCircle,
  CalendarRange,
  CheckCircle2,
  Circle,
  Loader2,
  MapPin,
  Plus,
  Route,
  Users,
  Wallet,
  X,
} from 'lucide-react';
import { memo, useEffect, useRef } from 'react';
import type { DateRange } from 'react-day-picker';

import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { formatBudgetValue, formatDateForDisplay } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';

import { EditableField } from './EditableField';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type TripInputsDraft = {
  destinations: string[];
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  traveler_count?: string | null;
  budget?: string | null;
  vibes?: string[];
};

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const FIELD_LABELS: Record<string, string> = {
  origin: 'From',
  destinations: 'Where to',
  dates: 'Dates',
  traveler_count: 'Travelers',
  budget: 'Budget',
  vibes: 'Vibes',
  multi_city_intent: 'Trip style',
};

// Core fields for progress calculation (excludes optional vibes/multi_city)
const CORE_PROGRESS_FIELDS = ['destinations', 'dates'] as const;
const OPTIONAL_PROGRESS_FIELDS = ['origin', 'traveler_count', 'budget'] as const;

export const calculateFormProgress = (tripInputs: DocumentTripInputs): { filled: number; total: number; percentage: number } => {
  const coreFields = CORE_PROGRESS_FIELDS.map(f => isFieldComplete(f, tripInputs));
  const optionalFields = OPTIONAL_PROGRESS_FIELDS.map(f => isFieldComplete(f, tripInputs));

  // Core fields are required, optional fields add bonus progress
  const coreComplete = coreFields.filter(Boolean).length;
  const optionalComplete = optionalFields.filter(Boolean).length;

  const filled = coreComplete + optionalComplete;
  const total = CORE_PROGRESS_FIELDS.length + OPTIONAL_PROGRESS_FIELDS.length;
  const percentage = Math.round((filled / total) * 100);

  return { filled, total, percentage };
};

// Date presets for quick date selection
export type DatePreset = {
  label: string;
  getDates: () => DateRange;
};

// ─────────────────────────────────────────────────────────────────────────────
// Helper Functions
// ─────────────────────────────────────────────────────────────────────────────

const isFieldComplete = (field: string, tripInputs: DocumentTripInputs): boolean => {
  switch (field) {
    case 'origin':
      return Boolean(tripInputs.origin);
    case 'destinations':
      return (tripInputs.destinations ?? []).length > 0;
    case 'dates':
      return Boolean(tripInputs.start_date) && Boolean(tripInputs.end_date);
    case 'traveler_count':
      return tripInputs.traveler_count != null;
    case 'budget':
      return tripInputs.budget != null;
    case 'vibes':
      return (tripInputs.vibes ?? []).length > 0;
    case 'multi_city_intent':
      return tripInputs.multi_city_intent != null;
    default:
      return false;
  }
};

const formatTravelers = (value?: number | null) =>
  value != null ? `${value} traveler${value === 1 ? '' : 's'}` : null;

export const toTripInputsDraft = (inputs: DocumentTripInputs): TripInputsDraft => {
  return {
    destinations: inputs.destinations ?? [],
    origin: inputs.origin ?? null,
    start_date: inputs.start_date ?? null,
    end_date: inputs.end_date ?? null,
    traveler_count: inputs.traveler_count != null ? String(inputs.traveler_count) : null,
    budget: inputs.budget != null ? String(inputs.budget) : null,
    vibes: inputs.vibes ?? [],
  };
};

// ─────────────────────────────────────────────────────────────────────────────
// LocationBadge Component
// ─────────────────────────────────────────────────────────────────────────────

interface LocationBadgeProps {
  type: 'origin' | 'destination';
  index?: number;
  value: string;
  isOrigin?: boolean;
  isSelected: boolean;
  onSelect: (key: 'origin' | number | null) => void;
  onRemove: () => void;
}

const LocationBadge = memo(function LocationBadge({
  type,
  index,
  value,
  isOrigin = false,
  isSelected,
  onSelect,
  onRemove,
}: LocationBadgeProps) {
  const badgeKey = type === 'origin' ? 'origin' : index!;
  const badgeRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (isSelected && badgeRef.current) {
      badgeRef.current.focus();
    }
  }, [isSelected]);

  const handleRemoveClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onRemove();
  };

  return (
    <span
      ref={badgeRef}
      className={`group relative inline-flex cursor-pointer items-center gap-1 text-xs font-semibold transition-all outline-none ${
        isSelected
          ? 'bg-primary/20 rounded-full px-1.5 py-0.5 ring-primary ring-2 ring-offset-1'
          : 'hover:bg-muted/60 rounded-full px-1 py-0.5'
      }`}
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(isSelected ? null : badgeKey);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Delete' || e.key === 'Backspace') {
          e.preventDefault();
          onRemove();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          onSelect(null);
          badgeRef.current?.blur();
        } else if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(isSelected ? null : badgeKey);
        }
      }}
    >
      <MapPin
        className={`h-3 w-3 shrink-0 ${isOrigin ? 'text-muted-foreground' : 'text-accent'}`}
      />
      {value}
      <button
        type="button"
        onClick={handleRemoveClick}
        className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gray-500 text-white opacity-0 transition-opacity hover:bg-gray-600 group-hover:opacity-70"
        aria-label={`Remove ${value}`}
      >
        <X className="h-2.5 w-2.5" />
      </button>
    </span>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// TripDetailsForm Props
// ─────────────────────────────────────────────────────────────────────────────

export interface TripDetailsFormProps {
  // Core data
  tripInputs: DocumentTripInputs;
  tripInputsDraft: TripInputsDraft;
  editingField: keyof TripInputsDraft | null;

  // Derived state passed down
  hasOrigin: boolean;
  hasDestination: boolean;
  hasDates: boolean;
  hasStartDate: boolean;
  hasEndDate: boolean;
  calendarOpen: boolean;
  selectedDateRange: DateRange | undefined;
  previewDays: Date[];
  hasDateValidationWarning: boolean;
  selectedLocationBadge: 'origin' | number | null;
  datePresets: DatePreset[];

  // Input state
  originInput: string;
  originInputExpanded: boolean;
  destinationInput: string;
  destinationInputExpanded: boolean;

  // Pending validation state
  pendingOrigin: string | null;
  pendingDestination: string | null;

  // Callbacks for editing
  onStartEditingField: (field: keyof TripInputsDraft) => void;
  onFieldChange: (field: keyof TripInputsDraft, value: string) => void;
  onCommitField: (field?: keyof TripInputsDraft, value?: string) => Promise<void>;
  setTripInputsDraft: React.Dispatch<React.SetStateAction<TripInputsDraft>>;
  setEditingField: React.Dispatch<React.SetStateAction<keyof TripInputsDraft | null>>;

  // Origin callbacks
  onSetOrigin: (origin: string) => void;
  onRemoveOrigin: () => void;
  setOriginInput: (v: string) => void;
  setOriginInputExpanded: (v: boolean) => void;

  // Destination callbacks
  onAddDestination: (destination: string) => void;
  onRemoveDestination: (index: number) => void;
  setDestinationInput: (v: string) => void;
  setDestinationInputExpanded: (v: boolean) => void;

  // Multi-city
  onToggleMultiCity: () => void;

  // Calendar callbacks
  onCalendarOpenChange: (open: boolean) => void;
  onCalendarDayClick: (day: Date) => void;
  onCalendarDayMouseEnter: (day: Date) => void;
  onCalendarMouseLeave: () => void;
  onDatePresetClick: (range: DateRange) => void;
  onResetDates: () => void;

  // Other field callbacks
  onRemoveTravelerCount: () => void;
  onRemoveBudget: () => void;
  onSelectLocationBadge: (key: 'origin' | number | null) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// TripDetailsForm Component
// ─────────────────────────────────────────────────────────────────────────────

function TripDetailsFormInner({
  tripInputs,
  tripInputsDraft,
  editingField,
  hasOrigin,
  hasDestination,
  hasDates,
  hasStartDate,
  hasEndDate,
  calendarOpen,
  selectedDateRange,
  previewDays,
  hasDateValidationWarning,
  selectedLocationBadge,
  datePresets,
  originInput,
  originInputExpanded,
  destinationInput,
  destinationInputExpanded,
  pendingOrigin,
  pendingDestination,
  onStartEditingField,
  onFieldChange,
  onCommitField,
  setTripInputsDraft,
  setEditingField,
  onSetOrigin,
  onRemoveOrigin,
  setOriginInput,
  setOriginInputExpanded,
  onAddDestination,
  onRemoveDestination,
  setDestinationInput,
  setDestinationInputExpanded,
  onToggleMultiCity,
  onCalendarOpenChange,
  onCalendarDayClick,
  onCalendarDayMouseEnter,
  onCalendarMouseLeave,
  onDatePresetClick,
  onResetDates,
  onRemoveTravelerCount,
  onRemoveBudget,
  onSelectLocationBadge,
}: TripDetailsFormProps) {
  const draftBase = tripInputsDraft ?? toTripInputsDraft(tripInputs);

  // Parse calendar dates for defaultMonth
  const calendarStartDate = selectedDateRange?.from;
  const calendarEndDate = selectedDateRange?.to;

  // Calculate form progress
  const progress = calculateFormProgress(tripInputs);

  return (
    <div className="space-y-3">
      {/* Progress indicator */}
      <div className="flex items-center gap-3">
        <div className="flex-1 h-1.5 bg-muted/40 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-primary to-accent transition-all duration-500 ease-out rounded-full"
            style={{ width: `${progress.percentage}%` }}
            role="progressbar"
            aria-valuenow={progress.percentage}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Trip details ${progress.percentage}% complete`}
          />
        </div>
        <span className="text-xs text-muted-foreground tabular-nums shrink-0">
          {progress.filled}/{progress.total} details
        </span>
      </div>

      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
      {/* From field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('origin', tripInputs) || pendingOrigin ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('origin', tripInputs) || pendingOrigin ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('origin', tripInputs) || pendingOrigin ? 'font-medium' : ''}>{FIELD_LABELS.origin}</span>
        </div>
        {hasOrigin ? (
          <div
            className="border-border/60 bg-muted/40 inline-flex items-center gap-1 rounded-full border px-2.5 py-1.5"
            onClick={() => onSelectLocationBadge(null)}
            onKeyDown={() => {}}
            role="presentation"
          >
            <LocationBadge
              type="origin"
              value={tripInputs.origin!}
              isOrigin
              isSelected={selectedLocationBadge === 'origin'}
              onSelect={onSelectLocationBadge}
              onRemove={onRemoveOrigin}
            />
          </div>
        ) : pendingOrigin ? (
          /* Show pending origin with loading spinner */
          <div
            className="border-primary/40 bg-primary/10 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 animate-pulse"
          >
            <Loader2 className="h-3 w-3 text-primary animate-spin" />
            <span className="text-xs font-semibold text-primary/80">{pendingOrigin}</span>
          </div>
        ) : originInputExpanded ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onSetOrigin(originInput);
              setOriginInputExpanded(false);
            }}
            className="inline-flex items-center"
          >
            <input
              type="text"
              value={originInput}
              onChange={(e) => setOriginInput(e.target.value)}
              placeholder="Enter city..."
              className="w-28 rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
              autoFocus
              onBlur={() => {
                setTimeout(() => {
                  if (!originInput.trim()) {
                    setOriginInputExpanded(false);
                  }
                }, 150);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onSetOrigin(originInput);
                  setOriginInputExpanded(false);
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setOriginInput('');
                  setOriginInputExpanded(false);
                }
              }}
            />
            {originInput.trim() && (
              <button
                type="submit"
                className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white hover:bg-primary/90 transition-colors"
                aria-label="Set origin"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            )}
          </form>
        ) : (
          <div
            className="border-border/40 bg-muted/20 hover:border-primary/40 hover:bg-primary/5 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5 transition-colors"
            onClick={() => setOriginInputExpanded(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setOriginInputExpanded(true);
              }
            }}
            role="button"
            tabIndex={0}
          >
            <MapPin className="h-3 w-3 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/60 italic">e.g. New York</span>
          </div>
        )}
      </div>

      {/* Where to field */}
      <div className="group flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('destinations', tripInputs) || pendingDestination ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('destinations', tripInputs) || pendingDestination ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('destinations', tripInputs) || pendingDestination ? 'font-medium' : ''}>{FIELD_LABELS.destinations}</span>
        </div>
        {hasDestination || pendingDestination ? (
          <div className="inline-flex items-center">
            <div
              className="border-border/60 bg-muted/40 inline-flex flex-wrap items-center gap-1 rounded-full border px-2.5 py-1.5"
              onClick={() => onSelectLocationBadge(null)}
              onKeyDown={() => {}}
              role="presentation"
            >
              {(tripInputs.destinations ?? []).map((dest, idx) => (
                <LocationBadge
                  key={`dest-${idx}`}
                  type="destination"
                  index={idx}
                  value={dest}
                  isSelected={selectedLocationBadge === idx}
                  onSelect={onSelectLocationBadge}
                  onRemove={() => onRemoveDestination(idx)}
                />
              ))}
              {/* Show pending destination with loading spinner */}
              {pendingDestination && (
                <span className="inline-flex items-center gap-1 rounded-full px-1 py-0.5 animate-pulse">
                  <Loader2 className="h-3 w-3 text-accent animate-spin" />
                  <span className="text-xs font-semibold text-accent/80">{pendingDestination}</span>
                </span>
              )}
            </div>
            {/* Add destination button / input */}
            {destinationInputExpanded ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  onAddDestination(destinationInput);
                  setDestinationInputExpanded(false);
                }}
                className="inline-flex items-center ml-1.5"
              >
                <input
                  type="text"
                  value={destinationInput}
                  onChange={(e) => setDestinationInput(e.target.value)}
                  placeholder="Add destination..."
                  className="w-28 rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
                  autoFocus
                  onBlur={() => {
                    setTimeout(() => {
                      if (!destinationInput.trim()) {
                        setDestinationInputExpanded(false);
                      }
                    }, 150);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      onAddDestination(destinationInput);
                      setDestinationInputExpanded(false);
                    } else if (e.key === 'Escape') {
                      e.preventDefault();
                      setDestinationInput('');
                      setDestinationInputExpanded(false);
                    }
                  }}
                />
                {destinationInput.trim() && (
                  <button
                    type="submit"
                    className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white hover:bg-primary/90 transition-colors"
                    aria-label="Add destination"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                )}
              </form>
            ) : (
              <button
                type="button"
                onClick={() => setDestinationInputExpanded(true)}
                className="-ml-2 flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-primary/40 bg-card text-primary/60 hover:border-primary/60 hover:bg-primary/10 hover:text-primary transition-all opacity-0 group-hover:opacity-100 shadow-sm"
                aria-label="Add destination"
                title="Add another destination"
              >
                <Plus className="h-3 w-3" />
              </button>
            )}
          </div>
        ) : destinationInputExpanded ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onAddDestination(destinationInput);
              setDestinationInputExpanded(false);
            }}
            className="inline-flex items-center"
          >
            <input
              type="text"
              value={destinationInput}
              onChange={(e) => setDestinationInput(e.target.value)}
              placeholder="Enter destination..."
              className="w-28 rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
              autoFocus
              onBlur={() => {
                setTimeout(() => {
                  if (!destinationInput.trim()) {
                    setDestinationInputExpanded(false);
                  }
                }, 150);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onAddDestination(destinationInput);
                  setDestinationInputExpanded(false);
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setDestinationInput('');
                  setDestinationInputExpanded(false);
                }
              }}
            />
            {destinationInput.trim() && (
              <button
                type="submit"
                className="ml-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white hover:bg-primary/90 transition-colors"
                aria-label="Add destination"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            )}
          </form>
        ) : (
          <div
            className="border-border/40 bg-muted/20 hover:border-primary/40 hover:bg-primary/5 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5 transition-colors"
            onClick={() => setDestinationInputExpanded(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setDestinationInputExpanded(true);
              }
            }}
            role="button"
            tabIndex={0}
          >
            <MapPin className="h-3 w-3 text-muted-foreground/40" />
            <span className="text-xs text-muted-foreground/60 italic">e.g. Paris</span>
          </div>
        )}
      </div>

      {/* Multi-city toggle (only shown when 2+ destinations) */}
      {(tripInputs.destinations ?? []).length >= 2 && (
        <div className="flex flex-col gap-1">
          <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('multi_city_intent', tripInputs) ? 'text-accent' : 'text-muted-foreground/40'}`}>
            {isFieldComplete('multi_city_intent', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3 opacity-60" strokeDasharray="2 2" />}
            <span className={isFieldComplete('multi_city_intent', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.multi_city_intent}</span>
            {!isFieldComplete('multi_city_intent', tripInputs) && <span className="text-[10px] text-muted-foreground/40">(optional)</span>}
          </div>
          <button
            type="button"
            onClick={onToggleMultiCity}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 cursor-pointer transition-colors ${
              tripInputs.multi_city_intent === 'multi_city'
                ? 'border-accent/40 bg-accent/10 text-accent'
                : 'border-border/60 bg-muted/40 text-foreground'
            }`}
          >
            <Route className="h-3.5 w-3.5" />
            <span className="text-xs font-semibold">
              {tripInputs.multi_city_intent === 'multi_city' ? 'One itinerary' : 'Separate options'}
            </span>
          </button>
        </div>
      )}

      {/* Dates field */}
      <div className="flex flex-col gap-1">
        <div className={`flex items-center gap-1 text-xs transition-colors ${isFieldComplete('dates', tripInputs) ? 'text-accent' : 'text-muted-foreground/60'}`}>
          {isFieldComplete('dates', tripInputs) ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
          <span className={isFieldComplete('dates', tripInputs) ? 'font-medium' : ''}>{FIELD_LABELS.dates}</span>
        </div>
        {hasDates ? (
          <Popover open={calendarOpen} onOpenChange={onCalendarOpenChange}>
            <PopoverTrigger asChild>
              <div
                className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1.5 transition-colors ${
                  hasDateValidationWarning
                    ? 'border-orange-400/60 bg-orange-50 hover:bg-orange-100'
                    : 'border-border/60 bg-muted/40 hover:bg-muted/60'
                }`}
                role="button"
                tabIndex={0}
                title={hasDateValidationWarning ? 'One or more dates are in the past' : undefined}
              >
                {hasDateValidationWarning ? (
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 text-orange-500" />
                ) : (
                  <CalendarRange className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
                )}
                <span className={`whitespace-nowrap text-xs font-semibold ${hasDateValidationWarning ? 'text-orange-700' : 'text-foreground'}`}>
                  {hasStartDate && formatDateForDisplay(tripInputs.start_date)}
                  {hasStartDate && hasEndDate && ' – '}
                  {hasEndDate && formatDateForDisplay(tripInputs.end_date)}
                </span>
              </div>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <div className="flex">
                {/* Quick preset buttons */}
                <div className="flex flex-col gap-1 border-r border-border/60 p-2">
                  <span className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Quick picks
                  </span>
                  {datePresets.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => onDatePresetClick(preset.getDates())}
                      className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-foreground hover:bg-muted transition-colors"
                    >
                      {preset.label}
                    </button>
                  ))}
                  {/* Reset button to clear dates and allow re-selection */}
                  {(calendarStartDate || calendarEndDate) && (
                    <>
                      <div className="my-1 border-t border-border/40" />
                      <button
                        type="button"
                        onClick={onResetDates}
                        className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                      >
                        Reset dates
                      </button>
                    </>
                  )}
                </div>
                <div onMouseLeave={onCalendarMouseLeave}>
                  <Calendar
                    mode="range"
                    defaultMonth={calendarStartDate ?? new Date()}
                    selected={selectedDateRange}
                    onSelect={() => {}}
                    onDayClick={onCalendarDayClick}
                    onDayMouseEnter={onCalendarDayMouseEnter}
                    numberOfMonths={2}
                    disabled={{ before: new Date() }}
                    modifiers={{ preview: previewDays }}
                    modifiersClassNames={{ preview: 'bg-muted/50' }}
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>
        ) : (
          <Popover open={calendarOpen} onOpenChange={onCalendarOpenChange}>
            <PopoverTrigger asChild>
              <div
                className="border-border/40 bg-muted/20 hover:border-primary/40 hover:bg-primary/5 inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-dashed px-2.5 py-1.5 transition-colors"
                role="button"
                tabIndex={0}
              >
                <CalendarRange className="h-3.5 w-3.5 text-muted-foreground/40" />
                <span className="text-xs text-muted-foreground/60 italic">e.g. Dec 15-22</span>
              </div>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <div className="flex">
                {/* Quick preset buttons */}
                <div className="flex flex-col gap-1 border-r border-border/60 p-2">
                  <span className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Quick picks
                  </span>
                  {datePresets.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => onDatePresetClick(preset.getDates())}
                      className="whitespace-nowrap rounded-md px-3 py-1.5 text-left text-xs font-medium text-foreground hover:bg-muted transition-colors"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <div onMouseLeave={onCalendarMouseLeave}>
                  <Calendar
                    mode="range"
                    defaultMonth={new Date()}
                    selected={selectedDateRange}
                    onSelect={() => {}}
                    onDayClick={onCalendarDayClick}
                    onDayMouseEnter={onCalendarDayMouseEnter}
                    numberOfMonths={2}
                    disabled={{ before: new Date() }}
                    modifiers={{ preview: previewDays }}
                    modifiersClassNames={{ preview: 'bg-muted/50' }}
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>
        )}
      </div>

      {/* Travelers field (optional) */}
      <EditableField
        label={FIELD_LABELS.traveler_count}
        icon={Users}
        placeholder="#"
        emptyPlaceholder="e.g. 2"
        isComplete={isFieldComplete('traveler_count', tripInputs)}
        isEditing={editingField === 'traveler_count'}
        draftValue={draftBase.traveler_count == null ? '' : String(draftBase.traveler_count)}
        displayValue={tripInputs.traveler_count != null ? (formatTravelers(tripInputs.traveler_count) ?? '') : ''}
        hasValue={tripInputs.traveler_count != null}
        onStartEditing={() => onStartEditingField('traveler_count')}
        onValueChange={(value) => onFieldChange('traveler_count', value)}
        onCommit={(value) => onCommitField('traveler_count', value)}
        onCancel={() => {
          const originalValue = tripInputs.traveler_count;
          setTripInputsDraft((prev) =>
            prev ? { ...prev, traveler_count: originalValue != null ? String(originalValue) : null } : prev
          );
          setEditingField(null);
        }}
        onRemove={onRemoveTravelerCount}
      />

      {/* Budget field (optional) */}
      <EditableField
        label={FIELD_LABELS.budget}
        icon={Wallet}
        placeholder="$"
        emptyPlaceholder="e.g. $3000"
        isComplete={isFieldComplete('budget', tripInputs)}
        isEditing={editingField === 'budget'}
        draftValue={draftBase.budget == null ? '' : String(draftBase.budget)}
        displayValue={tripInputs.budget != null ? formatBudgetValue(tripInputs.budget) : ''}
        hasValue={tripInputs.budget != null}
        onStartEditing={() => onStartEditingField('budget')}
        onValueChange={(value) => onFieldChange('budget', value)}
        onCommit={(value) => onCommitField('budget', value)}
        onCancel={() => {
          const originalValue = tripInputs.budget;
          setTripInputsDraft((prev) =>
            prev ? { ...prev, budget: originalValue != null ? String(originalValue) : null } : prev
          );
          setEditingField(null);
        }}
        onRemove={onRemoveBudget}
      />
      </div>
    </div>
  );
}

export const TripDetailsForm = memo(TripDetailsFormInner);
