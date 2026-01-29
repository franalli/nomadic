'use client';

import { Calendar, Check, DollarSign, MapPin, Plane } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface OnboardingChipsProps {
  /** Current destination value (if set) */
  destination?: string;
  /** Current origin value (if set) */
  origin?: string;
  /** Formatted date range string (if set) */
  dateRange?: string;
  /** Budget description (if set) */
  budget?: string;
  /** Whether user has chosen flexible dates */
  dateFlex?: boolean;
  /** Trip duration in days (for flexible dates display) */
  tripDuration?: number;
  /** Callback when destination chip is clicked */
  onDestinationClick?: () => void;
  /** Callback when origin chip is clicked */
  onOriginClick?: () => void;
  /** Callback when dates chip is clicked */
  onDatesClick?: () => void;
  /** Callback when budget chip is clicked */
  onBudgetClick?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Chip Component (internal)
// ─────────────────────────────────────────────────────────────────────────────

interface ChipProps {
  icon: typeof MapPin;
  label: string;
  value?: string;
  onClick?: () => void;
  disabled?: boolean;
}

const Chip = memo(function Chip({ icon: Icon, label, value, onClick, disabled = false }: ChipProps) {
  const hasValue = !!value;

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        // Base chip styling per spec (h-7 = 28px)
        'inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full',
        'transition-all duration-200 ease-out active:scale-[0.98]',
        // State-based styling - monochromatic design
        hasValue
          // Active/Filled state: zinc border with filled look
          ? cn(
              'border border-zinc-900 bg-zinc-100 text-zinc-900 font-semibold',
              'dark:border-white/30 dark:bg-white/10 dark:text-white'
            )
          // Inactive/Default state: subtle, clickable appearance
          : cn(
              'border border-zinc-200 bg-white text-zinc-500',
              'dark:border-white/10 dark:bg-transparent dark:text-zinc-400'
            ),
        // Hover states
        !hasValue && !disabled && 'hover:border-zinc-400 dark:hover:border-white/30',
        hasValue && !disabled && 'hover:bg-zinc-200 dark:hover:bg-white/15',
        // Disabled state
        disabled && 'opacity-40 cursor-not-allowed',
        // Focus visible ring
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-900/20 dark:focus-visible:ring-white/20'
      )}
    >
      <Icon
        className={cn(
          'h-3.5 w-3.5 flex-shrink-0',
          hasValue ? 'text-zinc-900 dark:text-white' : 'text-zinc-400 dark:text-zinc-500'
        )}
      />
      <span className="text-xs truncate max-w-[120px]">
        {value || label}
      </span>
      {hasValue && <Check className="h-2.5 w-2.5 text-zinc-900 dark:text-white" />}
    </button>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// OnboardingChips Component
//
// State inspectors above the main input - fixed order: Destination → Origin → Dates → Budget
// Empty state: subdued (per spec)
// Filled state: stronger contrast
// On click: opens picker (handled by parent)
// ─────────────────────────────────────────────────────────────────────────────

export const OnboardingChips = memo(function OnboardingChips({
  destination,
  origin,
  dateRange,
  budget,
  dateFlex,
  tripDuration,
  onDestinationClick,
  onOriginClick,
  onDatesClick,
  onBudgetClick,
}: OnboardingChipsProps) {
  // Compute flexible dates label if date_flex is set
  const flexDateLabel = dateFlex
    ? (tripDuration ? `~${tripDuration} days` : 'Flexible')
    : undefined;

  return (
    <div className="flex flex-wrap gap-2 mb-2">
      {/* Fixed order per spec: Destination → Origin → Dates → Budget */}
      <Chip
        icon={MapPin}
        label="Destination"
        value={destination}
        onClick={onDestinationClick}
      />

      <Chip
        icon={Plane}
        label="Origin"
        value={origin}
        onClick={onOriginClick}
      />

      <Chip
        icon={Calendar}
        label="Dates"
        value={dateRange || flexDateLabel}
        onClick={onDatesClick}
      />

      <Chip
        icon={DollarSign}
        label="Budget"
        value={budget}
        onClick={onBudgetClick}
      />
    </div>
  );
});

export default OnboardingChips;
