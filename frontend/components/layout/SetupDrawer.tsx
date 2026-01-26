'use client';

import { AnimatePresence, motion } from 'framer-motion';
import {
  Calendar,
  Check,
  Clock,
  DollarSign,
  MapPin,
  Plane,
  Users,
} from 'lucide-react';
import { memo } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn, formatDateForDisplay } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import { isBookingEnabled } from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface ChecklistItem {
  id: string;
  label: string;
  value?: string | null;
  isRequired: boolean;
  isOptional?: boolean;
  helperText?: string;
  valueHelper?: string | null;
  isSet: boolean;
  icon: typeof MapPin;
  onSet?: () => void;
}

interface SetupDrawerProps {
  onSetDestination?: () => void;
  onSetOrigin?: () => void;
  onSetDates?: () => void;
  onSetTravelers?: () => void;
  onSetBudget?: () => void;
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Animation Variants
// ─────────────────────────────────────────────────────────────────────────────

const drawerVariants = {
  hidden: {
    opacity: 0,
    y: -8,
    height: 0,
  },
  visible: {
    opacity: 1,
    y: 0,
    height: 'auto',
    transition: {
      duration: 0.25,
      ease: [0.4, 0, 0.2, 1],
    },
  },
  exit: {
    opacity: 0,
    y: -8,
    height: 0,
    transition: {
      duration: 0.2,
      ease: [0.4, 0, 1, 1],
    },
  },
};

const backdropVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
};

// ─────────────────────────────────────────────────────────────────────────────
// Checklist Row Component
// ─────────────────────────────────────────────────────────────────────────────

function ChecklistRow({ item }: { item: ChecklistItem }) {
  const Icon = item.icon;

  return (
    <div
      className={cn(
        'flex items-center gap-3 px-3 py-2.5 rounded-md transition-all',
        'bg-[rgba(0,0,0,0.02)] border border-[rgba(0,0,0,0.06)]',
        'dark:bg-[rgba(255,255,255,0.03)] dark:border-[rgba(255,255,255,0.06)]',
        !item.isSet &&
          item.onSet &&
          'cursor-pointer hover:bg-[rgba(0,0,0,0.04)] dark:hover:bg-[rgba(255,255,255,0.05)]'
      )}
      onClick={!item.isSet ? item.onSet : undefined}
    >
      {/* Status indicator */}
      <div
        className={cn(
          'w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0',
          item.isSet
            ? 'bg-emerald-500/20 text-emerald-500'
            : 'bg-muted/50 text-muted-foreground'
        )}
      >
        {item.isSet ? (
          <Check className="w-3 h-3" />
        ) : (
          <Icon className="w-3 h-3" />
        )}
      </div>

      {/* Label and value */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              'text-sm',
              item.isSet
                ? 'text-[var(--theme-text)]'
                : 'text-[var(--theme-text-muted)]'
            )}
          >
            {item.label}
          </span>
          {item.isOptional && !item.isSet && (
            <span className="text-xs text-muted-foreground">(optional)</span>
          )}
        </div>
        {item.isSet && item.value && (
          <p className="text-xs text-emerald-600 dark:text-emerald-400 truncate">
            {item.value}
            {item.valueHelper && (
              <span className="text-muted-foreground ml-1">
                ({item.valueHelper})
              </span>
            )}
          </p>
        )}
        {!item.isSet && item.helperText && (
          <p className="text-xs text-muted-foreground mt-0.5">
            {item.helperText}
          </p>
        )}
      </div>

      {/* Set button */}
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

// ─────────────────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * SetupDrawer - Slide-down drawer showing setup checklist.
 *
 * Triggered from the SetupProgressIndicator in the mobile header.
 * Shows the same checklist items as NextStepPanel but in drawer format.
 */
function SetupDrawerInner({
  onSetDestination,
  onSetOrigin,
  onSetDates,
  onSetTravelers,
  onSetBudget,
  className,
}: SetupDrawerProps) {
  const { isSetupDrawerOpen, closeSetupDrawer, isDesktop } = useMobileMode();
  const tripInputs = useDocumentTripInputs();

  // Don't render on desktop
  if (isDesktop) {
    return null;
  }

  // Extract values from store (same logic as NextStepPanel)
  const destination = tripInputs?.destination ?? null;
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

  const { nightsDisplay, dateRangeHelper } = (() => {
    if (endDate && startDate) {
      const start = new Date(startDate);
      const end = new Date(endDate);
      const nights = Math.round(
        (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)
      );
      const startFormatted = formatDateForDisplay(startDate);
      const endFormatted = formatDateForDisplay(endDate);
      return {
        nightsDisplay: `${nights} night${nights !== 1 ? 's' : ''}`,
        dateRangeHelper: `${startFormatted} - ${endFormatted}`,
      };
    }
    if (tripDuration && startDate) {
      const start = new Date(startDate);
      const end = new Date(start);
      end.setDate(end.getDate() + tripDuration);
      const startFormatted = formatDateForDisplay(startDate);
      const endFormatted = formatDateForDisplay(end.toISOString().split('T')[0]);
      return {
        nightsDisplay: `${tripDuration} night${tripDuration !== 1 ? 's' : ''}`,
        dateRangeHelper: `${startFormatted} - ${endFormatted}`,
      };
    }
    if (tripDuration) {
      return {
        nightsDisplay: `${tripDuration} night${tripDuration !== 1 ? 's' : ''}`,
        dateRangeHelper: null,
      };
    }
    return { nightsDisplay: null, dateRangeHelper: null };
  })();

  const travelersDisplay = (() => {
    if (adults === 1 && children === 0) return '1 adult';
    const parts: string[] = [];
    if (adults > 0) parts.push(`${adults} adult${adults !== 1 ? 's' : ''}`);
    if (children > 0)
      parts.push(`${children} child${children !== 1 ? 'ren' : ''}`);
    return parts.join(', ') || '1 adult';
  })();

  const budgetDisplay =
    budget != null
      ? new Intl.NumberFormat('en-US', {
          style: 'currency',
          currency,
          maximumFractionDigits: 0,
        }).format(budget)
      : null;

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
      onSet: () => {
        closeSetupDrawer();
        onSetDestination?.();
      },
    },
    {
      id: 'origin',
      label: 'Origin',
      value: origin,
      isRequired: isFlightsEnabled,
      isOptional: !isFlightsEnabled,
      helperText: !isFlightsEnabled
        ? 'Required when Flights is enabled'
        : undefined,
      isSet: !!origin,
      icon: Plane,
      onSet: () => {
        closeSetupDrawer();
        onSetOrigin?.();
      },
    },
    {
      id: 'startDate',
      label: 'Start date',
      value: startDateDisplay,
      isRequired: true,
      isSet: !!startDate,
      icon: Calendar,
      onSet: () => {
        closeSetupDrawer();
        onSetDates?.();
      },
    },
    {
      id: 'nights',
      label: 'Nights',
      value: nightsDisplay,
      isRequired: false,
      isOptional: true,
      helperText: 'Needed to price stays + build itinerary',
      valueHelper: dateRangeHelper,
      isSet: hasTripLength,
      icon: Clock,
      onSet: () => {
        closeSetupDrawer();
        onSetDates?.();
      },
    },
    {
      id: 'travelers',
      label: 'Travelers',
      value: travelersDisplay,
      isRequired: false,
      isSet: true,
      icon: Users,
      onSet: () => {
        closeSetupDrawer();
        onSetTravelers?.();
      },
    },
    {
      id: 'budget',
      label: 'Budget',
      value: budgetDisplay,
      isRequired: false,
      isOptional: true,
      isSet: !!budget,
      icon: DollarSign,
      onSet: () => {
        closeSetupDrawer();
        onSetBudget?.();
      },
    },
  ];

  return (
    <AnimatePresence>
      {isSetupDrawerOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            key="setup-drawer-backdrop"
            className={cn(
              'fixed inset-0 z-[1050]',
              'bg-black/20 backdrop-blur-sm',
              'lg:hidden'
            )}
            variants={backdropVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={closeSetupDrawer}
          />

          {/* Drawer */}
          <motion.div
            key="setup-drawer"
            className={cn(
              'fixed left-0 right-0 z-[1051]',
              'top-[calc(48px+env(safe-area-inset-top))]', // Below header
              'px-4 pb-4',
              'lg:hidden',
              className
            )}
            variants={drawerVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
          >
            <div
              className={cn(
                'rounded-xl overflow-hidden',
                'bg-[rgba(255,255,255,0.95)] border border-[rgba(0,0,0,0.08)]',
                'shadow-[0_8px_32px_rgba(0,0,0,0.12)]',
                'dark:bg-[rgba(20,20,20,0.95)] dark:border-[rgba(255,255,255,0.08)]',
                'dark:shadow-[0_8px_32px_rgba(0,0,0,0.4)]',
                'backdrop-blur-xl'
              )}
            >
              {/* Title */}
              <div className="px-4 pt-4 pb-2">
                <h3 className="text-sm font-medium text-[var(--theme-text)]">
                  Setup checklist
                </h3>
              </div>

              {/* Checklist */}
              <div className="px-4 pb-4 space-y-1.5">
                {items.map((item) => (
                  <ChecklistRow key={item.id} item={item} />
                ))}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

export const SetupDrawer = memo(SetupDrawerInner);
