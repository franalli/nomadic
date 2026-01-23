'use client';

import * as Collapsible from '@radix-ui/react-collapsible';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Bus,
  Car,
  ChevronDown,
  Hotel,
  Plane,
  Ticket,
  Train,
  Users,
} from 'lucide-react';
import { memo, useEffect, useState } from 'react';

import { ExpandablePill } from '@/components/pill/ExpandablePill';
import { BottomSheet } from '@/components/ui/bottom-sheet';
import { Switch } from '@/components/ui/switch';
import { useMobileMode } from '@/contexts/MobileModeContext';
import {
  getActivitiesSummary,
  getFlightsSummary,
  getHotelsSummary,
  getTransportSummary,
  getTravelersSummary,
} from '@/lib/refinementSummaries';
import { cn } from '@/lib/utils';
import type { LLMUpdatableField } from '@/state/documentStore';
import {
  isBookingEnabled,
  type ActivitySettings,
  type BookingTypes,
  type DocumentTripInputs,
  type FlightSettings,
  type HotelSettings,
  type TransportSettings,
} from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// Constants
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

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface OptionalRefinementsSectionProps {
  tripInputs: DocumentTripInputs;

  // Core input state for gating
  hasDestination: boolean;
  hasDates: boolean;

  // Booking settings
  bookingTypes: BookingTypes;
  flightSettings: FlightSettings;
  hotelSettings: HotelSettings;
  activitySettings: ActivitySettings;
  transportSettings: TransportSettings;

  // Update callbacks
  onUpdateBookingTypes: (settings: Partial<BookingTypes>) => void;
  onUpdateFlightSettings: (settings: Partial<FlightSettings>) => void;
  onUpdateHotelSettings: (settings: Partial<HotelSettings>) => void;
  onUpdateTransportSettings: (settings: Partial<TransportSettings>) => void;
  onAddActivity: (activity: string) => void;
  onRemoveActivity: (index: number) => void;
  onUpdateAdults: (value: number | null) => void;
  onUpdateChildren: (value: number | null) => void;
  onToggleRequiresAssistance: () => void;

  // LLM update tracking
  llmUpdatedFields?: Set<LLMUpdatableField>;
  onAcknowledgeLLMUpdate?: (field: LLMUpdatableField) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helper: Count active refinements
// ─────────────────────────────────────────────────────────────────────────────

function countActiveRefinements(
  bookingTypes: BookingTypes,
  activitySettings: ActivitySettings,
  tripInputs: DocumentTripInputs
): number {
  let count = 0;
  if (isBookingEnabled(bookingTypes.flights)) count++;
  if (isBookingEnabled(bookingTypes.hotels)) count++;
  if (isBookingEnabled(bookingTypes.ground_transport)) count++;
  if (isBookingEnabled(bookingTypes.activities) || activitySettings.categories.length > 0) count++;
  if (tripInputs.adults != null || tripInputs.children != null) count++;
  // Budget is now a core constraint, not a refinement
  return count;
}

// ─────────────────────────────────────────────────────────────────────────────
// Popover Content Wrapper
// ─────────────────────────────────────────────────────────────────────────────

interface PopoverContentWrapperProps {
  hint?: string;
  onReset?: () => void;
  children: React.ReactNode;
}

function PopoverContentWrapper({ hint, onReset, children }: PopoverContentWrapperProps) {
  return (
    <div className="flex flex-col gap-2">
      {hint && (
        <p className="text-[10px] text-muted-foreground/60 mb-1">{hint}</p>
      )}
      {children}
      {onReset && (
        <button
          type="button"
          onClick={onReset}
          className="text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors self-start mt-1"
        >
          Reset
        </button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Gating Message Component
// ─────────────────────────────────────────────────────────────────────────────

interface GatingMessageProps {
  show: boolean;
  hasDestination: boolean;
  hasDates: boolean;
}

function GatingMessage({ show, hasDestination, hasDates }: GatingMessageProps) {
  if (!show) return null;

  const missing: string[] = [];
  if (!hasDestination) missing.push('destination');
  if (!hasDates) missing.push('dates');

  return (
    <p className="text-[10px] text-amber-600 mt-1">
      Set {missing.join(' + ')} to fetch options
    </p>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────────────────

function OptionalRefinementsSectionInner({
  tripInputs,
  hasDestination,
  hasDates,
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  transportSettings,
  onUpdateBookingTypes,
  onUpdateFlightSettings,
  onUpdateHotelSettings,
  onUpdateTransportSettings,
  onAddActivity,
  onRemoveActivity,
  onUpdateAdults,
  onUpdateChildren,
  onToggleRequiresAssistance,
  llmUpdatedFields,
  onAcknowledgeLLMUpdate,
}: OptionalRefinementsSectionProps) {
  const { isDesktop } = useMobileMode();

  // Collapsible state - desktop expanded, mobile collapsed
  const [isOpen, setIsOpen] = useState(true);

  // Sync default state when breakpoint changes
  useEffect(() => {
    setIsOpen(isDesktop);
  }, [isDesktop]);

  // Pill open states
  const [flightsOpen, setFlightsOpen] = useState(false);
  const [transportOpen, setTransportOpen] = useState(false);
  const [hotelsOpen, setHotelsOpen] = useState(false);
  const [activitiesOpen, setActivitiesOpen] = useState(false);
  const [travelersOpen, setTravelersOpen] = useState(false);

  // Activity input
  const [activityInput, setActivityInput] = useState('');

  // LLM update helpers
  const isFieldLLMUpdated = (field: LLMUpdatableField) =>
    llmUpdatedFields?.has(field) ?? false;
  const isSubFieldUpdated = (field: string) =>
    llmUpdatedFields?.has(field as LLMUpdatableField) ?? false;
  const acknowledgeField = (field: LLMUpdatableField) => {
    if (onAcknowledgeLLMUpdate && llmUpdatedFields?.has(field)) {
      onAcknowledgeLLMUpdate(field);
    }
  };

  // Active count for badge
  const activeCount = countActiveRefinements(bookingTypes, activitySettings, tripInputs);

  // Gating state
  const needsCoreInputs = !hasDestination || !hasDates;

  // Summaries
  const flightsSummary = getFlightsSummary(flightSettings, bookingTypes.flights);
  const hotelsSummary = getHotelsSummary(hotelSettings, bookingTypes.hotels);
  const transportSummary = getTransportSummary(transportSettings, bookingTypes.ground_transport);
  const activitiesSummary = getActivitiesSummary(activitySettings, bookingTypes.activities);
  const travelersSummary = getTravelersSummary(
    tripInputs.adults,
    tripInputs.children,
    tripInputs.requires_assistance
  );

  // Reset handlers - set to 'off' for tri-state model
  const resetFlights = () => {
    onUpdateBookingTypes({ flights: 'off' });
    onUpdateFlightSettings({
      round_trip: true,
      cabin_class: 'economy',
      direct_only: false,
    });
  };

  const resetHotels = () => {
    onUpdateBookingTypes({ hotels: 'off' });
    onUpdateHotelSettings({ min_stars: 0, amenities: [] });
  };

  const resetTransport = () => {
    onUpdateBookingTypes({ ground_transport: 'off' });
    onUpdateTransportSettings({ car: false, train: false, bus: false });
  };

  const resetActivities = () => {
    onUpdateBookingTypes({ activities: 'off' });
    // Clear all activity categories
    for (let i = activitySettings.categories.length - 1; i >= 0; i--) {
      onRemoveActivity(i);
    }
  };

  const resetTravelers = () => {
    onUpdateAdults(null);
    onUpdateChildren(null);
    if (tripInputs.requires_assistance) {
      onToggleRequiresAssistance();
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Popover content builders
  // ─────────────────────────────────────────────────────────────────────────

  const flightsContent = (
    <PopoverContentWrapper hint="Optional. Improves flight results." onReset={resetFlights}>
      <label className="flex items-center gap-2">
        <Switch
          checked={isBookingEnabled(bookingTypes.flights)}
          onCheckedChange={(checked) => {
            onUpdateBookingTypes({ flights: checked ? 'on' : 'off' });
            acknowledgeField('booking_types.flights' as LLMUpdatableField);
          }}
        />
        <span className="text-[11px] text-muted-foreground">Book flights</span>
      </label>
      <GatingMessage
        show={isBookingEnabled(bookingTypes.flights) && needsCoreInputs}
        hasDestination={hasDestination}
        hasDates={hasDates}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            onUpdateFlightSettings({ round_trip: !flightSettings.round_trip });
            acknowledgeField('flight_settings.round_trip' as LLMUpdatableField);
          }}
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200',
            flightSettings.round_trip
              ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
              : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
          )}
        >
          {flightSettings.round_trip ? 'Round trip' : 'One way'}
        </button>
        <button
          type="button"
          onClick={() => {
            onUpdateFlightSettings({ direct_only: !flightSettings.direct_only });
            acknowledgeField('flight_settings.direct_only' as LLMUpdatableField);
          }}
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200',
            flightSettings.direct_only
              ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
              : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
          )}
        >
          {flightSettings.direct_only ? 'Direct only' : 'Any stops'}
        </button>
        <select
          value={flightSettings.cabin_class}
          onChange={(e) => {
            onUpdateFlightSettings({
              cabin_class: e.target.value as FlightSettings['cabin_class'],
            });
            acknowledgeField('flight_settings.cabin_class' as LLMUpdatableField);
          }}
          className="rounded-full border border-border/40 bg-muted/20 px-2 py-1 text-[11px] text-foreground focus:border-primary/40 focus:outline-none"
        >
          <option value="economy">Economy</option>
          <option value="premium_economy">Premium</option>
          <option value="business">Business</option>
          <option value="first">First</option>
        </select>
      </div>
    </PopoverContentWrapper>
  );

  const transportContent = (
    <PopoverContentWrapper hint="Optional. Improves transport results." onReset={resetTransport}>
      <label className="flex items-center gap-2">
        <Switch
          checked={isBookingEnabled(bookingTypes.ground_transport)}
          onCheckedChange={(checked) => {
            onUpdateBookingTypes({ ground_transport: checked ? 'on' : 'off' });
            acknowledgeField('booking_types.ground_transport' as LLMUpdatableField);
          }}
        />
        <span className="text-[11px] text-muted-foreground">Book transport</span>
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            onUpdateTransportSettings({ car: !transportSettings.car });
            acknowledgeField('transport_settings.car' as LLMUpdatableField);
          }}
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200',
            transportSettings.car
              ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
              : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
          )}
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
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200',
            transportSettings.train
              ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
              : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
          )}
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
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] transition-all duration-200',
            transportSettings.bus
              ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary shadow-pill-active'
              : 'border-border/40 bg-gradient-to-b from-card/80 to-muted/20 text-muted-foreground shadow-pill hover:from-card hover:to-muted/40 hover:border-border/60 hover:shadow-pill-hover'
          )}
        >
          <Bus className="h-3 w-3" />
          Bus
        </button>
      </div>
    </PopoverContentWrapper>
  );

  const hotelsContent = (
    <PopoverContentWrapper hint="Optional. Improves hotel results." onReset={resetHotels}>
      <label className="flex items-center gap-2">
        <Switch
          checked={isBookingEnabled(bookingTypes.hotels)}
          onCheckedChange={(checked) => {
            onUpdateBookingTypes({ hotels: checked ? 'on' : 'off' });
            acknowledgeField('booking_types.hotels' as LLMUpdatableField);
          }}
        />
        <span className="text-[11px] text-muted-foreground">Book hotels</span>
      </label>
      <GatingMessage
        show={isBookingEnabled(bookingTypes.hotels) && needsCoreInputs}
        hasDestination={hasDestination}
        hasDates={hasDates}
      />
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground">Min stars:</span>
          <div className="flex gap-1">
            {[0, 1, 2, 3, 4, 5].map((stars) => (
              <button
                key={stars}
                type="button"
                onClick={() => {
                  onUpdateHotelSettings({ min_stars: stars });
                  acknowledgeField('hotel_settings.min_stars' as LLMUpdatableField);
                }}
                className={cn(
                  'w-6 h-6 rounded-full text-[10px] transition-all duration-200',
                  hotelSettings.min_stars === stars
                    ? 'border border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary'
                    : 'border border-border/40 bg-muted/20 text-muted-foreground hover:border-border/60'
                )}
              >
                {stars === 0 ? 'Any' : stars}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {HOTEL_AMENITIES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                const newAmenities = hotelSettings.amenities.includes(value)
                  ? hotelSettings.amenities.filter((a) => a !== value)
                  : [...hotelSettings.amenities, value];
                onUpdateHotelSettings({ amenities: newAmenities });
                acknowledgeField('hotel_settings.amenities' as LLMUpdatableField);
              }}
              className={cn(
                'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] transition-all duration-200',
                hotelSettings.amenities.includes(value)
                  ? 'border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 text-primary'
                  : 'border-border/40 bg-muted/20 text-muted-foreground hover:border-border/60'
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </PopoverContentWrapper>
  );

  const activitiesContent = (
    <PopoverContentWrapper hint="Optional. Improves activity results." onReset={resetActivities}>
      <label className="flex items-center gap-2">
        <Switch
          checked={isBookingEnabled(bookingTypes.activities)}
          onCheckedChange={(checked) => {
            onUpdateBookingTypes({ activities: checked ? 'on' : 'off' });
            acknowledgeField('booking_types.activities' as LLMUpdatableField);
          }}
        />
        <span className="text-[11px] text-muted-foreground">Book activities</span>
      </label>
      <div className="flex flex-wrap gap-1.5">
        {activitySettings.categories.map((category, index) => (
          <button
            key={category}
            type="button"
            onClick={() => onRemoveActivity(index)}
            className="inline-flex items-center gap-1 rounded-full border border-primary/50 bg-gradient-to-b from-primary/15 to-primary/10 px-2 py-0.5 text-[10px] text-primary"
          >
            {category}
            <span className="text-primary/60">&times;</span>
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={activityInput}
          onChange={(e) => setActivityInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && activityInput.trim()) {
              onAddActivity(activityInput.trim().toLowerCase());
              setActivityInput('');
            }
          }}
          placeholder="Add activity type..."
          className="flex-1 rounded-full border border-border/40 bg-muted/20 px-3 py-1 text-[11px] placeholder:text-muted-foreground/50 focus:border-primary/40 focus:outline-none"
        />
      </div>
    </PopoverContentWrapper>
  );

  const travelersContent = (
    <PopoverContentWrapper hint="Optional. Helps with group bookings." onReset={resetTravelers}>
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">Adults</span>
          <input
            type="number"
            min="1"
            max="20"
            value={tripInputs.adults ?? ''}
            onChange={(e) => {
              const val = e.target.value ? parseInt(e.target.value, 10) : null;
              onUpdateAdults(val);
            }}
            className="w-16 rounded-full border border-border/40 bg-muted/20 px-2 py-1 text-center text-[11px] focus:border-primary/40 focus:outline-none"
          />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">Children</span>
          <input
            type="number"
            min="0"
            max="20"
            value={tripInputs.children ?? ''}
            onChange={(e) => {
              const val = e.target.value ? parseInt(e.target.value, 10) : null;
              onUpdateChildren(val);
            }}
            className="w-16 rounded-full border border-border/40 bg-muted/20 px-2 py-1 text-center text-[11px] focus:border-primary/40 focus:outline-none"
          />
        </div>
        <label className="flex items-center gap-2">
          <Switch
            checked={tripInputs.requires_assistance ?? false}
            onCheckedChange={() => onToggleRequiresAssistance()}
          />
          <span className="text-[11px] text-muted-foreground">Requires assistance</span>
        </label>
      </div>
    </PopoverContentWrapper>
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Render chip with mobile/desktop switching
  // ─────────────────────────────────────────────────────────────────────────

  const renderChip = (
    label: string,
    icon: typeof Plane,
    isChipOpen: boolean,
    setChipOpen: (open: boolean) => void,
    hasValue: boolean,
    isLLMUpdated: boolean,
    onAcknowledge: () => void,
    summary: string | undefined,
    content: React.ReactNode
  ) => {
    if (isDesktop) {
      return (
        <ExpandablePill
          label={label}
          icon={icon}
          isOpen={isChipOpen}
          onOpenChange={setChipOpen}
          hasValue={hasValue}
          isLLMUpdated={isLLMUpdated}
          onAcknowledge={onAcknowledge}
          summary={summary}
          expandedContent={content}
        />
      );
    }

    // Mobile: Use ExpandablePill as trigger but render BottomSheet
    return (
      <>
        <button
          type="button"
          onClick={() => setChipOpen(true)}
          data-filled={hasValue}
          className={cn(
            'group inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full',
            'transition-all duration-[120ms] ease-out active:scale-[0.98]',
            hasValue
              ? 'border border-[var(--chip-active-border)] bg-[var(--chip-active-bg)] text-[var(--chip-active-text)] font-semibold'
              : 'border border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)]',
            !hasValue && 'hover:border-[var(--chip-border-hover)]'
          )}
        >
          {(() => {
            const Icon = icon;
            return (
              <Icon
                className={cn(
                  'h-3.5 w-3.5 transition-colors duration-150',
                  hasValue ? 'text-[var(--chip-active-icon)]' : ''
                )}
              />
            );
          })()}
          <span
            className={cn(
              'text-xs transition-colors duration-150',
              hasValue ? 'font-semibold' : 'font-medium'
            )}
          >
            {label}
          </span>
          {summary && hasValue && (
            <span className="text-[10px] text-muted-foreground/70 truncate max-w-[80px]">
              · {summary}
            </span>
          )}
          <ChevronDown className="h-3.5 w-3.5" />
        </button>
        <BottomSheet
          open={isChipOpen}
          onOpenChange={setChipOpen}
          title={label}
          hint="Optional. Improves results."
        >
          {content}
        </BottomSheet>
      </>
    );
  };

  // Gate visibility: show disabled hint when core inputs missing
  const canShowRefinements = hasDestination && hasDates;

  if (!canShowRefinements) {
    return (
      <div className="flex items-center gap-1.5 py-1.5 px-3 text-xs text-muted-foreground/50 border border-dashed border-border/30 rounded-lg">
        <span>Optional refinements</span>
        <span className="text-[10px]">· Set destination + dates to unlock</span>
      </div>
    );
  }

  return (
    <Collapsible.Root open={isOpen} onOpenChange={setIsOpen} className="w-full">
      <Collapsible.Trigger asChild>
        <button
          type="button"
          className={cn(
            'w-full flex items-center justify-between py-1.5 px-3',
            'text-xs font-medium text-[var(--theme-text-muted)]',
            'border border-[var(--theme-hairline)] rounded-lg',
            'hover:bg-[var(--theme-overlay)] transition-colors'
          )}
        >
          <span className="flex items-center gap-1.5">
            Refinements
            <span className="text-[10px] text-muted-foreground/60">· {activeCount}</span>
          </span>
          <ChevronDown
            className={cn(
              'h-4 w-4 transition-transform duration-200',
              isOpen && 'rotate-180'
            )}
          />
        </button>
      </Collapsible.Trigger>

      <AnimatePresence initial={false}>
        {isOpen && (
          <Collapsible.Content forceMount asChild>
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: 'easeInOut' }}
              className="overflow-hidden"
            >
              <div
                className={cn(
                  'pt-3 pb-1',
                  isDesktop
                    ? 'flex flex-wrap gap-2'
                    : 'grid grid-cols-2 gap-2'
                )}
              >
                {renderChip(
                  'Flights',
                  Plane,
                  flightsOpen,
                  setFlightsOpen,
                  isBookingEnabled(bookingTypes.flights),
                  isFieldLLMUpdated('flight_settings') || isSubFieldUpdated('booking_types.flights'),
                  () => {
                    acknowledgeField('flight_settings');
                    acknowledgeField('booking_types' as LLMUpdatableField);
                    acknowledgeField('booking_types.flights' as LLMUpdatableField);
                  },
                  flightsSummary,
                  flightsContent
                )}
                {renderChip(
                  'Transport',
                  Car,
                  transportOpen,
                  setTransportOpen,
                  isBookingEnabled(bookingTypes.ground_transport),
                  isFieldLLMUpdated('transport_settings') || isSubFieldUpdated('booking_types.ground_transport'),
                  () => {
                    acknowledgeField('transport_settings');
                    acknowledgeField('booking_types' as LLMUpdatableField);
                    acknowledgeField('booking_types.ground_transport' as LLMUpdatableField);
                  },
                  transportSummary,
                  transportContent
                )}
                {renderChip(
                  'Hotels',
                  Hotel,
                  hotelsOpen,
                  setHotelsOpen,
                  isBookingEnabled(bookingTypes.hotels),
                  isFieldLLMUpdated('hotel_settings') || isSubFieldUpdated('booking_types.hotels'),
                  () => {
                    acknowledgeField('hotel_settings');
                    acknowledgeField('booking_types' as LLMUpdatableField);
                    acknowledgeField('booking_types.hotels' as LLMUpdatableField);
                  },
                  hotelsSummary,
                  hotelsContent
                )}
                {renderChip(
                  'Activities',
                  Ticket,
                  activitiesOpen,
                  setActivitiesOpen,
                  isBookingEnabled(bookingTypes.activities) || activitySettings.categories.length > 0,
                  isFieldLLMUpdated('activity_settings') || isSubFieldUpdated('booking_types.activities'),
                  () => {
                    acknowledgeField('activity_settings');
                    acknowledgeField('booking_types' as LLMUpdatableField);
                    acknowledgeField('booking_types.activities' as LLMUpdatableField);
                  },
                  activitiesSummary,
                  activitiesContent
                )}
                {renderChip(
                  'Travelers',
                  Users,
                  travelersOpen,
                  setTravelersOpen,
                  tripInputs.adults != null || tripInputs.children != null,
                  isFieldLLMUpdated('adults') || isFieldLLMUpdated('children') || isFieldLLMUpdated('requires_assistance'),
                  () => {
                    acknowledgeField('adults');
                    acknowledgeField('children');
                    acknowledgeField('requires_assistance');
                  },
                  travelersSummary,
                  travelersContent
                )}
              </div>
            </motion.div>
          </Collapsible.Content>
        )}
      </AnimatePresence>
    </Collapsible.Root>
  );
}

export const OptionalRefinementsSection = memo(OptionalRefinementsSectionInner);
