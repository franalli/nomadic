'use client';

import { Calendar, DollarSign, MapPin, Plane } from 'lucide-react';
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
        'transition-all duration-[120ms] ease-out active:scale-[0.98]',
        // State-based styling using theme tokens for light/dark mode support
        hasValue
          // Filled: stronger presence, font-weight 600
          ? 'border border-[var(--theme-border)] bg-[var(--theme-overlay)] font-semibold'
          // Empty (subdued): ~10% lower contrast - informational, not actionable
          : 'border border-[var(--theme-border)] bg-[var(--theme-surface-2)] opacity-70',
        // Text colors using theme tokens
        hasValue ? 'text-[var(--theme-text)]' : 'text-[var(--theme-text-muted)]',
        // Hover states
        !hasValue && !disabled && 'hover:opacity-90 hover:bg-[var(--theme-overlay)]',
        hasValue && !disabled && 'hover:opacity-100',
        // Disabled state
        disabled && 'opacity-40 cursor-not-allowed',
        // Focus visible ring
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/65'
      )}
    >
      <Icon
        className={cn(
          'h-3.5 w-3.5 flex-shrink-0',
          hasValue ? 'text-[#E2A23A]' : 'text-[var(--theme-text-muted)]' // State Amber when filled
        )}
      />
      <span className="text-xs truncate max-w-[120px]">
        {value || label}
      </span>
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
    <div className="flex flex-wrap gap-2 mb-3">
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
