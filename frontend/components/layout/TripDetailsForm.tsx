'use client';

import {
  AlertCircle,
  Bus,
  CalendarRange,
  Car,
  Hotel,
  Loader2,
  MapPin,
  Plane,
  Route,
  Ticket,
  Train,
  Users,
  Wallet,
  X,
} from 'lucide-react';
import { memo, useState } from 'react';
import type { DateRange } from 'react-day-picker';

import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Switch } from '@/components/ui/switch';
import { ExpandablePill } from '@/components/pill/ExpandablePill';
import { InlineEditPill } from '@/components/pill/InlineEditPill';
import { LocationBadge } from '@/components/pill/LocationBadge';
import { TruncatedDestinationList } from '@/components/pill/TruncatedDestinationList';
import { formatDateForDisplay } from '@/lib/utils';
import type { LLMUpdatableField } from '@/state/documentStore';
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

const CURRENCY_OPTIONS = [
  { value: 'USD', label: 'USD ($)' },
  { value: 'EUR', label: 'EUR (€)' },
  { value: 'GBP', label: 'GBP (£)' },
  { value: 'CAD', label: 'CAD (CA$)' },
  { value: 'AUD', label: 'AUD (A$)' },
  { value: 'JPY', label: 'JPY (¥)' },
] as const;

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type TripInputsDraft = {
  destinations: string[];
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  adults?: string | null;
  children?: string | null;
  requires_assistance?: boolean | null;
  budget?: string | null;
  currency?: string | null;
  vibes?: string[];
};

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const FIELD_LABELS: Record<string, string> = {
  origin: 'From',
  destinations: 'Where to',
  dates: 'Dates',
  travelers: 'Travelers',
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

export const toTripInputsDraft = (inputs: DocumentTripInputs): TripInputsDraft => {
  return {
    destinations: inputs.destinations ?? [],
    origin: inputs.origin ?? null,
    start_date: inputs.start_date ?? null,
    end_date: inputs.end_date ?? null,
    adults: inputs.adults != null ? String(inputs.adults) : null,
    children: inputs.children != null ? String(inputs.children) : null,
    requires_assistance: inputs.requires_assistance ?? null,
    budget: inputs.budget != null ? String(inputs.budget) : null,
    currency: inputs.currency ?? 'USD',
    vibes: inputs.vibes ?? [],
  };
};

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

  // Travelers callbacks
  onRemoveTravelers: () => void;
  onUpdateAdults: (value: number | null) => void;
  onUpdateChildren: (value: number | null) => void;
  onToggleRequiresAssistance: () => void;

  // Other field callbacks
  onRemoveBudget: () => void;
  onUpdateCurrency: (value: string) => void;
  onSelectLocationBadge: (key: 'origin' | number | null) => void;

  // Booking type toggles
  bookingTypes: BookingTypes;
  flightSettings: FlightSettings;
  hotelSettings: HotelSettings;
  activitySettings: ActivitySettings;
  transportSettings: TransportSettings;
  onUpdateBookingTypes: (settings: Partial<BookingTypes>) => void;
  onUpdateFlightSettings: (settings: Partial<FlightSettings>) => void;
  onUpdateHotelSettings: (settings: Partial<HotelSettings>) => void;
  onUpdateActivitySettings: (settings: Partial<ActivitySettings>) => void;
  onUpdateTransportSettings: (settings: Partial<TransportSettings>) => void;

  // LLM update tracking - fields that were recently updated by the planner
  llmUpdatedFields?: Set<LLMUpdatableField>;
  onAcknowledgeLLMUpdate?: (field: LLMUpdatableField) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// TripDetailsForm Component
// ─────────────────────────────────────────────────────────────────────────────

function TripDetailsFormInner({
  tripInputs,
  tripInputsDraft,
  editingField: _editingField,
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
  originInputExpanded: _originInputExpanded,
  destinationInput,
  destinationInputExpanded: _destinationInputExpanded,
  pendingOrigin,
  pendingDestination,
  onStartEditingField: _onStartEditingField,
  onFieldChange,
  onCommitField,
  setTripInputsDraft: _setTripInputsDraft,
  setEditingField: _setEditingField,
  onSetOrigin,
  onRemoveOrigin,
  setOriginInput,
  setOriginInputExpanded: _setOriginInputExpanded,
  onAddDestination,
  onRemoveDestination,
  setDestinationInput,
  setDestinationInputExpanded: _setDestinationInputExpanded,
  onToggleMultiCity,
  onCalendarOpenChange,
  onCalendarDayClick,
  onCalendarDayMouseEnter,
  onCalendarMouseLeave,
  onDatePresetClick,
  onResetDates,
  onRemoveTravelers: _onRemoveTravelers,
  onUpdateAdults,
  onUpdateChildren,
  onToggleRequiresAssistance,
  onRemoveBudget: _onRemoveBudget,
  onUpdateCurrency,
  onSelectLocationBadge,
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  transportSettings,
  onUpdateBookingTypes,
  onUpdateFlightSettings,
  onUpdateHotelSettings,
  onUpdateActivitySettings,
  onUpdateTransportSettings,
  llmUpdatedFields,
  onAcknowledgeLLMUpdate,
}: TripDetailsFormProps) {
  const draftBase = tripInputsDraft ?? toTripInputsDraft(tripInputs);

  // Helper to check if a field was updated by LLM
  const isFieldLLMUpdated = (field: LLMUpdatableField) => llmUpdatedFields?.has(field) ?? false;

  // Helper to check if a sub-field was updated by LLM (for individual controls)
  const isSubFieldUpdated = (field: string) => llmUpdatedFields?.has(field as LLMUpdatableField) ?? false;

  // Helper to acknowledge LLM update for a field
  const acknowledgeField = (field: LLMUpdatableField) => {
    if (onAcknowledgeLLMUpdate && llmUpdatedFields?.has(field)) {
      onAcknowledgeLLMUpdate(field);
    }
  };

  // Check if dates were updated (either start or end)
  const areDatesLLMUpdated = isFieldLLMUpdated('start_date') || isFieldLLMUpdated('end_date');
  const acknowledgeDates = () => {
    acknowledgeField('start_date');
    acknowledgeField('end_date');
  };
  const isBudgetLLMUpdated = isFieldLLMUpdated('budget') || isFieldLLMUpdated('currency');
  const acknowledgeBudget = () => {
    acknowledgeField('budget');
    acknowledgeField('currency');
  };

  // Parse calendar dates for defaultMonth
  const calendarStartDate = selectedDateRange?.from;

  // Collapsible open states for trip input pills (kept for remaining collapsible pills)
  const [multiCityPillOpen, setMultiCityPillOpen] = useState(false);
  const [travelersPillOpen, setTravelersPillOpen] = useState(false);
  const [budgetPillOpen, setBudgetPillOpen] = useState(false);

  // Collapsible open states for booking type settings
  const [flightsSettingsOpen, setFlightsSettingsOpen] = useState(false);
  const [hotelsSettingsOpen, setHotelsSettingsOpen] = useState(false);
  const [transportSettingsOpen, setTransportSettingsOpen] = useState(false);
  const [activitiesSettingsOpen, setActivitiesSettingsOpen] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      {/* Row 1: Always-visible inline editing pills */}
      <div className="grid grid-cols-3 gap-3 items-stretch">
        {/* From field - inline */}
        <InlineEditPill
          label="From"
          icon={MapPin}
          isLLMUpdated={isFieldLLMUpdated('origin')}
          onAcknowledge={() => acknowledgeField('origin')}
        >
          {hasOrigin && !pendingOrigin ? (
            <LocationBadge
              type="origin"
              value={tripInputs.origin!}
              isSelected={selectedLocationBadge === 'origin'}
              onSelect={onSelectLocationBadge}
              onRemove={onRemoveOrigin}
            />
          ) : pendingOrigin ? (
            <div className="inline-flex items-center gap-1.5 animate-pulse">
              <Loader2 className="h-3 w-3 text-primary animate-spin" />
              <span className="text-xs font-semibold text-primary/80">{pendingOrigin}</span>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (originInput.trim()) {
                  onSetOrigin(originInput);
                  setOriginInput('');
                }
              }}
              className="flex-1"
            >
              <input
                type="text"
                value={originInput}
                onChange={(e) => setOriginInput(e.target.value)}
                placeholder="Enter city..."
                className="w-full bg-transparent border-none text-sm placeholder:text-muted-foreground/50 focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    if (originInput.trim()) {
                      onSetOrigin(originInput);
                      setOriginInput('');
                    }
                  }
                }}
              />
            </form>
          )}
        </InlineEditPill>

        {/* Where to field - inline with truncation */}
        <InlineEditPill
          label="Where to"
          icon={MapPin}
          isLLMUpdated={isFieldLLMUpdated('destinations')}
          onAcknowledge={() => acknowledgeField('destinations')}
        >
          <TruncatedDestinationList
            destinations={tripInputs.destinations ?? []}
            maxVisible={2}
            selectedBadge={selectedLocationBadge}
            onSelectBadge={onSelectLocationBadge}
            onRemoveDestination={onRemoveDestination}
            destinationInput={destinationInput}
            setDestinationInput={setDestinationInput}
            onAddDestination={onAddDestination}
            hasDestination={hasDestination}
            pendingDestination={pendingDestination}
          />
        </InlineEditPill>

        {/* Dates field - inline with calendar popover */}
        <InlineEditPill
          label="Dates"
          icon={hasDateValidationWarning ? AlertCircle : CalendarRange}
          isLLMUpdated={areDatesLLMUpdated}
          onAcknowledge={acknowledgeDates}
        >
          <Popover open={calendarOpen} onOpenChange={onCalendarOpenChange}>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={`inline-flex items-center gap-1.5 text-sm font-medium cursor-pointer hover:text-primary transition-colors ${
                  hasDates ? 'text-foreground' : 'text-muted-foreground'
                }`}
              >
                {hasDates ? (
                  <>
                    {hasStartDate && formatDateForDisplay(tripInputs.start_date)}
                    {hasStartDate && hasEndDate && ' - '}
                    {hasEndDate && formatDateForDisplay(tripInputs.end_date)}
                  </>
                ) : (
                  'Select dates...'
                )}
              </button>
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
          {hasDates && (
            <button
              type="button"
              onClick={onResetDates}
              className="flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label="Clear dates"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </InlineEditPill>
      </div>

      {/* Row 2: Booking type expandable pills */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* Flights pill */}
        <ExpandablePill
          label="Flights"
          icon={Plane}
          isOpen={flightsSettingsOpen}
          onOpenChange={setFlightsSettingsOpen}
          isLLMUpdated={isFieldLLMUpdated('flight_settings')}
          onAcknowledge={() => acknowledgeField('flight_settings')}
          expandedContent={
              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2">
                  <Switch
                    checked={bookingTypes.flights}
                    onCheckedChange={(checked) => onUpdateBookingTypes({ flights: checked })}
                  />
                  <span className="text-[11px] text-muted-foreground">Include flights</span>
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      onUpdateFlightSettings({ round_trip: !flightSettings.round_trip });
                      acknowledgeField('flight_settings.round_trip' as LLMUpdatableField);
                    }}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200 ${
                      flightSettings.round_trip
                        ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                        : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                    } ${isSubFieldUpdated('flight_settings.round_trip') ? 'sparkle-control' : ''}`}
                  >
                    {flightSettings.round_trip ? 'Round trip' : 'One way'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onUpdateFlightSettings({ direct_only: !flightSettings.direct_only });
                      acknowledgeField('flight_settings.direct_only' as LLMUpdatableField);
                    }}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200 ${
                      flightSettings.direct_only
                        ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                        : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                    } ${isSubFieldUpdated('flight_settings.direct_only') ? 'sparkle-control' : ''}`}
                  >
                    {flightSettings.direct_only ? 'Direct only' : 'Any stops'}
                  </button>
                  <select
                    value={flightSettings.cabin_class}
                    onChange={(e) => {
                      onUpdateFlightSettings({ cabin_class: e.target.value as FlightSettings['cabin_class'] });
                      acknowledgeField('flight_settings.cabin_class' as LLMUpdatableField);
                    }}
                    className={`rounded-full border border-border/40 bg-muted/20 px-2 py-1 text-[11px] text-foreground focus:border-primary/40 focus:outline-none ${isSubFieldUpdated('flight_settings.cabin_class') ? 'sparkle-control' : ''}`}
                  >
                    <option value="economy">Economy</option>
                    <option value="premium_economy">Premium</option>
                    <option value="business">Business</option>
                    <option value="first">First</option>
                  </select>
                </div>
              </div>
            }
          />

          {/* Transport pill */}
          <ExpandablePill
            label="Transport"
            icon={Car}
            isOpen={transportSettingsOpen}
            onOpenChange={setTransportSettingsOpen}
            isLLMUpdated={isFieldLLMUpdated('transport_settings')}
            onAcknowledge={() => acknowledgeField('transport_settings')}
            expandedContent={
              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2">
                  <Switch
                    checked={bookingTypes.ground_transport}
                    onCheckedChange={(checked) => onUpdateBookingTypes({ ground_transport: checked })}
                  />
                  <span className="text-[11px] text-muted-foreground">Include transport</span>
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      onUpdateTransportSettings({ car: !transportSettings.car });
                      acknowledgeField('transport_settings.car' as LLMUpdatableField);
                    }}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200 ${
                      transportSettings.car
                        ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                        : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                    } ${isSubFieldUpdated('transport_settings.car') ? 'sparkle-control' : ''}`}
                  >
                    <Car className="h-3 w-3" />
                    Car
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onUpdateTransportSettings({ train: !transportSettings.train });
                      acknowledgeField('transport_settings.train' as LLMUpdatableField);
                    }}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200 ${
                      transportSettings.train
                        ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                        : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                    } ${isSubFieldUpdated('transport_settings.train') ? 'sparkle-control' : ''}`}
                  >
                    <Train className="h-3 w-3" />
                    Train
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onUpdateTransportSettings({ bus: !transportSettings.bus });
                      acknowledgeField('transport_settings.bus' as LLMUpdatableField);
                    }}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200 ${
                      transportSettings.bus
                        ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                        : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                    } ${isSubFieldUpdated('transport_settings.bus') ? 'sparkle-control' : ''}`}
                  >
                    <Bus className="h-3 w-3" />
                    Bus
                  </button>
                </div>
              </div>
            }
          />

          {/* Hotels pill */}
          <ExpandablePill
            label="Hotels"
            icon={Hotel}
            isOpen={hotelsSettingsOpen}
            onOpenChange={setHotelsSettingsOpen}
            isLLMUpdated={isFieldLLMUpdated('hotel_settings')}
            onAcknowledge={() => acknowledgeField('hotel_settings')}
            expandedContent={
              <div className="flex flex-col gap-3">
                <label className="flex items-center gap-2">
                  <Switch
                    checked={bookingTypes.hotels}
                    onCheckedChange={(checked) => onUpdateBookingTypes({ hotels: checked })}
                  />
                  <span className="text-[11px] text-muted-foreground">Include hotels</span>
                </label>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">Min stars:</span>
                  <div className={`flex gap-0.5 rounded-lg p-0.5 ${isSubFieldUpdated('hotel_settings.min_stars') ? 'sparkle-control' : ''}`}>
                    {[1, 2, 3, 4, 5].map((star) => (
                      <button
                        key={star}
                        type="button"
                        onClick={() => {
                          onUpdateHotelSettings({ min_stars: hotelSettings.min_stars === star ? 0 : star });
                          acknowledgeField('hotel_settings.min_stars' as LLMUpdatableField);
                        }}
                        className={`w-6 h-6 rounded text-[11px] font-medium transition-all duration-200 ${
                          star <= hotelSettings.min_stars
                            ? 'bg-gradient-to-b from-primary/20 to-primary/15 text-primary border border-primary/50 shadow-pill-active'
                            : 'bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground border border-border/40 shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                        }`}
                      >
                        {star}
                      </button>
                    ))}
                  </div>
                </div>
                <div className={`flex flex-wrap gap-1.5 rounded-lg p-0.5 ${isSubFieldUpdated('hotel_settings.amenities') ? 'sparkle-control' : ''}`}>
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
                          acknowledgeField('hotel_settings.amenities' as LLMUpdatableField);
                        }}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-all duration-200 ${
                          isSelected
                            ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                            : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
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
            isLLMUpdated={isFieldLLMUpdated('activity_settings')}
            onAcknowledge={() => acknowledgeField('activity_settings')}
            expandedContent={
              <div className="flex flex-col gap-3">
                <label className="flex items-center gap-2">
                  <Switch
                    checked={bookingTypes.activities}
                    onCheckedChange={(checked) => onUpdateBookingTypes({ activities: checked })}
                  />
                  <span className="text-[11px] text-muted-foreground">Include activities</span>
                </label>
                <div className={`flex flex-wrap gap-1.5 rounded-lg p-0.5 ${isSubFieldUpdated('activity_settings.categories') ? 'sparkle-control' : ''}`}>
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
                          acknowledgeField('activity_settings.categories' as LLMUpdatableField);
                        }}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-all duration-200 ${
                          isSelected
                            ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                            : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
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
                      acknowledgeField('activity_settings.max_duration_hours' as LLMUpdatableField);
                    }}
                    className={`rounded-full border border-border/40 bg-muted/20 px-2 py-0.5 text-[10px] text-foreground focus:border-primary/40 focus:outline-none ${isSubFieldUpdated('activity_settings.max_duration_hours') ? 'sparkle-control' : ''}`}
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

      {/* Row 3: Other trip input pills */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
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
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-all duration-200 ${
                    tripInputs.multi_city_intent === 'multi_city'
                      ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                      : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                  }`}
                >
                  Visit both
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (tripInputs.multi_city_intent === 'multi_city') onToggleMultiCity();
                  }}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-all duration-200 ${
                    tripInputs.multi_city_intent !== 'multi_city'
                      ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                      : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                  }`}
                >
                  Compare destinations
                </button>
              </>
            }
          />
        )}

        {/* Travelers field */}
        <ExpandablePill
          label={FIELD_LABELS.travelers}
          icon={Users}
          compact
          isOpen={travelersPillOpen}
          onOpenChange={setTravelersPillOpen}
          isLLMUpdated={isFieldLLMUpdated('adults') || isFieldLLMUpdated('children')}
          onAcknowledge={() => {
            acknowledgeField('adults');
            acknowledgeField('children');
          }}
          expandedContent={
            <div className="flex flex-col gap-2">
              {/* Adults input */}
              <div className="flex items-center gap-1.5">
                <label className="text-xs text-muted-foreground w-20">Adults</label>
                <input
                  type="number"
                  value={draftBase.adults ?? ''}
                  onChange={(e) => {
                    const value = e.target.value;
                    onFieldChange('adults', value);
                    if (value) {
                      const num = parseInt(value, 10);
                      if (!isNaN(num) && num >= 0) {
                        onUpdateAdults(num === 0 ? null : num);
                      }
                    } else {
                      onUpdateAdults(null);
                    }
                  }}
                  placeholder="0"
                  min={0}
                  className="w-16 rounded-full border border-primary/30 bg-gradient-to-b from-primary/5 to-primary/10 px-2 py-1 text-xs text-center placeholder:text-muted-foreground/50 shadow-sm transition-all duration-200 hover:border-primary/40 hover:shadow-pill focus:border-primary/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:ring-offset-1 focus:shadow-pill-active"
                />
              </div>
              {/* Children input */}
              <div className="flex items-center gap-1.5">
                <label className="text-xs text-muted-foreground w-20">Children</label>
                <input
                  type="number"
                  value={draftBase.children ?? ''}
                  onChange={(e) => {
                    const value = e.target.value;
                    onFieldChange('children', value);
                    if (value) {
                      const num = parseInt(value, 10);
                      if (!isNaN(num) && num >= 0) {
                        onUpdateChildren(num === 0 ? null : num);
                      }
                    } else {
                      onUpdateChildren(null);
                    }
                  }}
                  placeholder="0"
                  min={0}
                  className="w-16 rounded-full border border-primary/30 bg-gradient-to-b from-primary/5 to-primary/10 px-2 py-1 text-xs text-center placeholder:text-muted-foreground/50 shadow-sm transition-all duration-200 hover:border-primary/40 hover:shadow-pill focus:border-primary/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:ring-offset-1 focus:shadow-pill-active"
                />
              </div>
              {/* Requires assistance toggle */}
              <button
                type="button"
                onClick={() => onToggleRequiresAssistance()}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-all duration-200 self-start ${
                  tripInputs.requires_assistance
                    ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
                    : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
                }`}
              >
                Requires assistance
              </button>
            </div>
          }
        />

        {/* Budget field */}
        <ExpandablePill
          label={FIELD_LABELS.budget}
          icon={Wallet}
          compact
          isOpen={budgetPillOpen}
          onOpenChange={setBudgetPillOpen}
          isLLMUpdated={isBudgetLLMUpdated}
          onAcknowledge={acknowledgeBudget}
          expandedContent={
            <div className="flex items-center gap-2">
              <select
                value={draftBase.currency ?? 'USD'}
                onChange={(e) => {
                  onFieldChange('currency', e.target.value);
                  onUpdateCurrency(e.target.value);
                }}
                className="h-8 w-24 rounded-full border border-primary/30 bg-gradient-to-b from-primary/5 to-primary/10 px-3 text-xs font-medium text-foreground shadow-sm transition-all duration-200 hover:border-primary/40 hover:shadow-pill focus:border-primary/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:ring-offset-1 focus:shadow-pill-active"
              >
                {CURRENCY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <input
                type="number"
                value={draftBase.budget ?? ''}
                onChange={(e) => onFieldChange('budget', e.target.value)}
                placeholder="Budget"
                min={0}
                step={100}
                className="w-24 rounded-full border border-primary/30 bg-gradient-to-b from-primary/5 to-primary/10 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 shadow-sm transition-all duration-200 hover:border-primary/40 hover:shadow-pill focus:border-primary/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:ring-offset-1 focus:shadow-pill-active"
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
          }
        />
      </div>
    </div>
  );
}

export const TripDetailsForm = memo(TripDetailsFormInner);
