'use client';

import {
  AlertCircle,
  Bus,
  CalendarRange,
  Car,
  CheckCircle2,
  Circle,
  Hotel,
  Loader2,
  MapPin,
  Plane,
  Plus,
  Route,
  Ticket,
  Train,
  Users,
  Wallet,
  X,
} from 'lucide-react';
import { memo, useEffect, useRef, useState } from 'react';
import type { DateRange } from 'react-day-picker';

import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ExpandablePill } from '@/components/pill/ExpandablePill';
import { formatBudgetValue, formatDateForDisplay } from '@/lib/utils';
import type {
  ActivitySettings,
  BookingTypes,
  DocumentTripInputs,
  FlightSettings,
  HotelSettings,
  TransportSettings,
} from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// Constants for pill sub-inputs
// ─────────────────────────────────────────────────────────────────────────────

const HOTEL_AMENITIES = [
  { value: 'wifi', label: 'WiFi' },
  { value: 'pool', label: 'Pool' },
  { value: 'parking', label: 'Parking' },
  { value: 'gym', label: 'Gym' },
  { value: 'spa', label: 'Spa' },
  { value: 'breakfast', label: 'Breakfast' },
  { value: 'pet_friendly', label: 'Pet friendly' },
] as const;

const ACTIVITY_CATEGORIES = [
  { value: 'tours', label: 'Tours' },
  { value: 'experiences', label: 'Experiences' },
  { value: 'outdoor', label: 'Outdoor' },
  { value: 'cultural', label: 'Cultural' },
  { value: 'food_drink', label: 'Food & Drink' },
] as const;

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
  multi_city_intent: 'How to visit',
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
  value != null ? String(value) : null;

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

  // Booking type toggles
  bookingTypes: BookingTypes;
  flightSettings: FlightSettings;
  hotelSettings: HotelSettings;
  activitySettings: ActivitySettings;
  transportSettings: TransportSettings;
  onUpdateFlightSettings: (settings: Partial<FlightSettings>) => void;
  onUpdateHotelSettings: (settings: Partial<HotelSettings>) => void;
  onUpdateActivitySettings: (settings: Partial<ActivitySettings>) => void;
  onUpdateTransportSettings: (settings: Partial<TransportSettings>) => void;
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
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  transportSettings,
  onUpdateFlightSettings,
  onUpdateHotelSettings,
  onUpdateActivitySettings,
  onUpdateTransportSettings,
}: TripDetailsFormProps) {
  const draftBase = tripInputsDraft ?? toTripInputsDraft(tripInputs);

  // Parse calendar dates for defaultMonth
  const calendarStartDate = selectedDateRange?.from;
  const calendarEndDate = selectedDateRange?.to;

  // Collapsible open states for trip input pills
  const [originPillOpen, setOriginPillOpen] = useState(false);
  const [destinationPillOpen, setDestinationPillOpen] = useState(false);
  const [multiCityPillOpen, setMultiCityPillOpen] = useState(false);
  const [datesPillOpen, setDatesPillOpen] = useState(false);
  const [travelersPillOpen, setTravelersPillOpen] = useState(false);
  const [budgetPillOpen, setBudgetPillOpen] = useState(false);

  // Collapsible open states for booking type settings
  const [flightsSettingsOpen, setFlightsSettingsOpen] = useState(false);
  const [hotelsSettingsOpen, setHotelsSettingsOpen] = useState(false);
  const [transportSettingsOpen, setTransportSettingsOpen] = useState(false);
  const [activitiesSettingsOpen, setActivitiesSettingsOpen] = useState(false);

  // Handler for origin pill open change - populate input with current value
  const handleOriginPillOpenChange = (open: boolean) => {
    if (open && tripInputs.origin) {
      setOriginInput(tripInputs.origin);
    }
    setOriginPillOpen(open);
  };

  return (
    <div className="space-y-3">
      {/* What to book section - booking type expandable pills */}
      <div className="pb-2 border-b border-border/30">
        <div className="flex items-center gap-1 text-xs text-muted-foreground/60 mb-2">
          <span className="font-medium">What to book</span>
        </div>
        <div className="flex flex-wrap items-start gap-3">
          {/* Flights pill */}
          <ExpandablePill
            label="Flights"
            icon={Plane}

            isOpen={flightsSettingsOpen}
            onOpenChange={setFlightsSettingsOpen}
            expandedContent={
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onUpdateFlightSettings({ round_trip: !flightSettings.round_trip })}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-colors ${
                    flightSettings.round_trip
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                  }`}
                >
                  {flightSettings.round_trip ? 'Round trip' : 'One way'}
                </button>
                <button
                  type="button"
                  onClick={() => onUpdateFlightSettings({ direct_only: !flightSettings.direct_only })}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-colors ${
                    flightSettings.direct_only
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                  }`}
                >
                  {flightSettings.direct_only ? 'Direct only' : 'Any stops'}
                </button>
                <select
                  value={flightSettings.cabin_class}
                  onChange={(e) => onUpdateFlightSettings({ cabin_class: e.target.value as FlightSettings['cabin_class'] })}
                  className="rounded-full border border-border/40 bg-muted/20 px-2 py-1 text-[11px] text-foreground focus:border-primary/40 focus:outline-none"
                >
                  <option value="economy">Economy</option>
                  <option value="premium_economy">Premium</option>
                  <option value="business">Business</option>
                  <option value="first">First</option>
                </select>
              </div>
            }
          />

          {/* Transport pill */}
          <ExpandablePill
            label="Transport"
            icon={Car}

            isOpen={transportSettingsOpen}
            onOpenChange={setTransportSettingsOpen}
            expandedContent={
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onUpdateTransportSettings({ car: !transportSettings.car })}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-colors ${
                    transportSettings.car
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                  }`}
                >
                  <Car className="h-3 w-3" />
                  Car
                </button>
                <button
                  type="button"
                  onClick={() => onUpdateTransportSettings({ train: !transportSettings.train })}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-colors ${
                    transportSettings.train
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                  }`}
                >
                  <Train className="h-3 w-3" />
                  Train
                </button>
                <button
                  type="button"
                  onClick={() => onUpdateTransportSettings({ bus: !transportSettings.bus })}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-colors ${
                    transportSettings.bus
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                  }`}
                >
                  <Bus className="h-3 w-3" />
                  Bus
                </button>
              </div>
            }
          />

          {/* Hotels pill */}
          <ExpandablePill
            label="Hotels"
            icon={Hotel}

            isOpen={hotelsSettingsOpen}
            onOpenChange={setHotelsSettingsOpen}
            expandedContent={
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">Min stars:</span>
                  <div className="flex gap-0.5">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <button
                        key={star}
                        type="button"
                        onClick={() => onUpdateHotelSettings({ min_stars: hotelSettings.min_stars === star ? 0 : star })}
                        className={`w-6 h-6 rounded text-[11px] font-medium transition-colors ${
                          star <= hotelSettings.min_stars
                            ? 'bg-primary/20 text-primary border border-primary/40'
                            : 'bg-muted/20 text-muted-foreground border border-border/40 hover:bg-muted/40'
                        }`}
                      >
                        {star}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {HOTEL_AMENITIES.map((amenity) => {
                    const isSelected = hotelSettings.amenities.includes(amenity.value);
                    return (
                      <button
                        key={amenity.value}
                        type="button"
                        onClick={() => {
                          const newAmenities = isSelected
                            ? hotelSettings.amenities.filter((a) => a !== amenity.value)
                            : [...hotelSettings.amenities, amenity.value];
                          onUpdateHotelSettings({ amenities: newAmenities });
                        }}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                          isSelected
                            ? 'border-primary/40 bg-primary/10 text-primary'
                            : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                        }`}
                      >
                        {amenity.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            }
          />

          {/* Activities pill */}
          <ExpandablePill
            label="Activities"
            icon={Ticket}

            isOpen={activitiesSettingsOpen}
            onOpenChange={setActivitiesSettingsOpen}
            expandedContent={
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-1.5">
                  {ACTIVITY_CATEGORIES.map((category) => {
                    const isSelected = activitySettings.categories.includes(category.value);
                    return (
                      <button
                        key={category.value}
                        type="button"
                        onClick={() => {
                          const newCategories = isSelected
                            ? activitySettings.categories.filter((c) => c !== category.value)
                            : [...activitySettings.categories, category.value];
                          onUpdateActivitySettings({ categories: newCategories });
                        }}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                          isSelected
                            ? 'border-primary/40 bg-primary/10 text-primary'
                            : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                        }`}
                      >
                        {category.label}
                      </button>
                    );
                  })}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">Max duration:</span>
                  <select
                    value={activitySettings.max_duration_hours ?? ''}
                    onChange={(e) => {
                      const value = e.target.value;
                      onUpdateActivitySettings({
                        max_duration_hours: value === '' ? null : parseInt(value, 10)
                      });
                    }}
                    className="rounded-full border border-border/40 bg-muted/20 px-2 py-0.5 text-[10px] text-foreground focus:border-primary/40 focus:outline-none"
                  >
                    <option value="">No limit</option>
                    <option value="1">1 hour</option>
                    <option value="2">2 hours</option>
                    <option value="3">3 hours</option>
                    <option value="4">Half day (4h)</option>
                    <option value="8">Full day (8h)</option>
                  </select>
                </div>
              </div>
            }
          />
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
      {/* From field */}
      <ExpandablePill
        label={FIELD_LABELS.origin}
        icon={MapPin}

        isOpen={originPillOpen}
        onOpenChange={handleOriginPillOpenChange}
        expandedContent={
          <>
            {/* Current origin display */}
            {hasOrigin && !pendingOrigin && (
              <div className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-muted/40 px-2.5 py-1">
                <LocationBadge
                  type="origin"
                  value={tripInputs.origin!}
                  isOrigin
                  isSelected={selectedLocationBadge === 'origin'}
                  onSelect={onSelectLocationBadge}
                  onRemove={onRemoveOrigin}
                />
              </div>
            )}
            {pendingOrigin && (
              <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2.5 py-1 animate-pulse">
                <Loader2 className="h-3 w-3 text-primary animate-spin" />
                <span className="text-xs font-semibold text-primary/80">{pendingOrigin}</span>
              </div>
            )}
            {/* Input to set/change origin */}
            {!hasOrigin && !pendingOrigin && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (originInput.trim()) {
                    onSetOrigin(originInput);
                    setOriginInput('');
                  }
                }}
                className="inline-flex items-center"
              >
                <div className="relative inline-flex items-center">
                  <input
                    type="text"
                    value={originInput}
                    onChange={(e) => setOriginInput(e.target.value)}
                    placeholder="Enter city..."
                    className="w-28 rounded-full border border-primary/30 bg-primary/5 pl-3 pr-7 py-1 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        if (originInput.trim()) {
                          onSetOrigin(originInput);
                          setOriginInput('');
                        }
                      } else if (e.key === 'Escape') {
                        e.preventDefault();
                        setOriginPillOpen(false);
                      }
                    }}
                  />
                  <button
                    type="submit"
                    disabled={!originInput.trim()}
                    className="absolute right-1 flex h-5 w-5 items-center justify-center rounded-full text-primary/60 hover:text-primary hover:bg-primary/10 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-primary/60 transition-colors"
                    aria-label="Set origin"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </form>
            )}
          </>
        }
      />

      {/* Where to field */}
      <ExpandablePill
        label={FIELD_LABELS.destinations}
        icon={MapPin}

        isOpen={destinationPillOpen}
        onOpenChange={setDestinationPillOpen}
        expandedContent={
          <>
            {/* Current destinations display */}
            {(tripInputs.destinations ?? []).map((dest, idx) => (
              <div key={`dest-${idx}`} className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-muted/40 px-2.5 py-1">
                <LocationBadge
                  type="destination"
                  index={idx}
                  value={dest}
                  isSelected={selectedLocationBadge === idx}
                  onSelect={onSelectLocationBadge}
                  onRemove={() => onRemoveDestination(idx)}
                />
              </div>
            ))}
            {pendingDestination && (
              <div className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 animate-pulse">
                <Loader2 className="h-3 w-3 text-accent animate-spin" />
                <span className="text-xs font-semibold text-accent/80">{pendingDestination}</span>
              </div>
            )}
            {/* Input to add destination */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (destinationInput.trim()) {
                  onAddDestination(destinationInput);
                  setDestinationInput('');
                }
              }}
              className="inline-flex items-center"
            >
              <div className="relative inline-flex items-center">
                <input
                  type="text"
                  value={destinationInput}
                  onChange={(e) => setDestinationInput(e.target.value)}
                  placeholder={hasDestination ? "Add city..." : "Enter city..."}
                  className="w-28 rounded-full border border-primary/30 bg-primary/5 pl-3 pr-7 py-1 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      if (destinationInput.trim()) {
                        onAddDestination(destinationInput);
                        setDestinationInput('');
                      }
                    } else if (e.key === 'Escape') {
                      e.preventDefault();
                      setDestinationInput('');
                      setDestinationPillOpen(false);
                    }
                  }}
                />
                <button
                  type="submit"
                  disabled={!destinationInput.trim()}
                  className="absolute right-1 flex h-5 w-5 items-center justify-center rounded-full text-primary/60 hover:text-primary hover:bg-primary/10 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-primary/60 transition-colors"
                  aria-label="Add destination"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </form>
          </>
        }
      />

      {/* Multi-city toggle (only shown when 2+ destinations) */}
      {(tripInputs.destinations ?? []).length >= 2 && (
        <ExpandablePill
          label={FIELD_LABELS.multi_city_intent}
          icon={Route}

          isOpen={multiCityPillOpen}
          onOpenChange={setMultiCityPillOpen}
          expandedContent={
            <>
              <button
                type="button"
                onClick={() => {
                  if (tripInputs.multi_city_intent !== 'multi_city') onToggleMultiCity();
                }}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                  tripInputs.multi_city_intent === 'multi_city'
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                }`}
              >
                Visit both
              </button>
              <button
                type="button"
                onClick={() => {
                  if (tripInputs.multi_city_intent === 'multi_city') onToggleMultiCity();
                }}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                  tripInputs.multi_city_intent !== 'multi_city'
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40'
                }`}
              >
                Compare destinations
              </button>
            </>
          }
        />
      )}

      {/* Dates field */}
      <ExpandablePill
        label={FIELD_LABELS.dates}
        icon={hasDateValidationWarning ? AlertCircle : CalendarRange}

        isOpen={datesPillOpen}
        onOpenChange={setDatesPillOpen}
        expandedContent={
          <Popover open={calendarOpen} onOpenChange={onCalendarOpenChange}>
            <PopoverTrigger asChild>
              {hasDates ? (
                <button
                  type="button"
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 cursor-pointer transition-colors ${
                    hasDateValidationWarning
                      ? 'border-orange-400/60 bg-orange-50 hover:bg-orange-100'
                      : 'border-border/60 bg-muted/40 hover:bg-muted/60'
                  }`}
                >
                  <span className={`whitespace-nowrap text-xs font-semibold ${hasDateValidationWarning ? 'text-orange-700' : 'text-foreground'}`}>
                    {hasStartDate && formatDateForDisplay(tripInputs.start_date)}
                    {hasStartDate && hasEndDate && ' – '}
                    {hasEndDate && formatDateForDisplay(tripInputs.end_date)}
                  </span>
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      onResetDates();
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.stopPropagation();
                        onResetDates();
                      }
                    }}
                    className="flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                    aria-label="Clear dates"
                  >
                    <X className="h-3 w-3" />
                  </span>
                </button>
              ) : (
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/5 px-3 py-1 text-xs text-muted-foreground hover:border-primary/50 hover:bg-primary/10 transition-colors"
                >
                  <CalendarRange className="h-3.5 w-3.5" />
                  <span>Select dates</span>
                </button>
              )}
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
        }
      />

      {/* Travelers field */}
      <ExpandablePill
        label={FIELD_LABELS.traveler_count}
        icon={Users}

        isOpen={travelersPillOpen}
        onOpenChange={setTravelersPillOpen}
        expandedContent={
          <>
            {/* Current value display */}
            {tripInputs.traveler_count != null && (
              <div className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/40 px-2.5 py-1">
                <span className="text-xs font-semibold text-foreground">
                  {formatTravelers(tripInputs.traveler_count)}
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemoveTravelerCount();
                  }}
                  className="flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  aria-label="Clear travelers"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            )}
            {/* Input to set/change travelers */}
            <input
              type="number"
              value={draftBase.traveler_count ?? ''}
              onChange={(e) => onFieldChange('traveler_count', e.target.value)}
              placeholder="# travelers"
              min={1}
              className="w-24 rounded-full border border-primary/30 bg-primary/5 px-3 py-1 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onCommitField('traveler_count', (e.target as HTMLInputElement).value);
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setTravelersPillOpen(false);
                }
              }}
              onBlur={(e) => {
                onCommitField('traveler_count', e.target.value);
              }}
            />
          </>
        }
      />

      {/* Budget field */}
      <ExpandablePill
        label={FIELD_LABELS.budget}
        icon={Wallet}

        isOpen={budgetPillOpen}
        onOpenChange={setBudgetPillOpen}
        expandedContent={
          <>
            {/* Current value display */}
            {tripInputs.budget != null && (
              <div className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/40 px-2.5 py-1">
                <span className="text-xs font-semibold text-foreground">
                  {formatBudgetValue(tripInputs.budget)}
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemoveBudget();
                  }}
                  className="flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  aria-label="Clear budget"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            )}
            {/* Input to set/change budget */}
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">$</span>
              <input
                type="number"
                value={draftBase.budget ?? ''}
                onChange={(e) => onFieldChange('budget', e.target.value)}
                placeholder="Budget"
                min={0}
                className="w-28 rounded-full border border-primary/30 bg-primary/5 pl-6 pr-3 py-1 text-xs placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30 transition-all"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    onCommitField('budget', (e.target as HTMLInputElement).value);
                  } else if (e.key === 'Escape') {
                    e.preventDefault();
                    setBudgetPillOpen(false);
                  }
                }}
                onBlur={(e) => {
                  onCommitField('budget', e.target.value);
                }}
              />
            </div>
          </>
        }
      />
      </div>
    </div>
  );
}

export const TripDetailsForm = memo(TripDetailsFormInner);
