'use client';

import { ChevronDown } from 'lucide-react';
import { memo } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import { isBookingEnabled } from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface SetupProgressIndicatorProps {
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Progress Ring SVG Component
// ─────────────────────────────────────────────────────────────────────────────

function ProgressRing({
  progress,
  size = 24,
  strokeWidth = 2.5,
}: {
  progress: number; // 0-1
  size?: number;
  strokeWidth?: number;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const strokeDashoffset = circumference - progress * circumference;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="transform -rotate-90"
    >
      {/* Background circle */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        className="text-muted-foreground/20"
      />
      {/* Progress circle */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeDasharray={circumference}
        strokeDashoffset={strokeDashoffset}
        strokeLinecap="round"
        className="text-emerald-500 transition-all duration-300"
      />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * SetupProgressIndicator - Mobile header progress indicator for setup phase.
 *
 * Shows "2/5 Completed" with a circular progress ring.
 * Tappable to expand the setup drawer accordion.
 */
function SetupProgressIndicatorInner({ className }: SetupProgressIndicatorProps) {
  const { isSetupDrawerOpen, toggleSetupDrawer } = useMobileMode();
  const tripInputs = useDocumentTripInputs();

  // Calculate setup progress using same logic as NextStepPanel
  const isFlightsEnabled = isBookingEnabled(tripInputs?.booking_types?.flights);

  // Define all trackable items and their completion status
  const items = [
    { id: 'destination', isSet: !!tripInputs?.destination, isRequired: true },
    { id: 'origin', isSet: !!tripInputs?.origin, isRequired: isFlightsEnabled },
    { id: 'startDate', isSet: !!tripInputs?.start_date, isRequired: true },
    {
      id: 'nights',
      isSet: !!(tripInputs?.end_date || tripInputs?.trip_duration),
      isRequired: false,
    },
    { id: 'travelers', isSet: true, isRequired: false }, // Always has default
    { id: 'budget', isSet: !!tripInputs?.budget, isRequired: false },
  ];

  // Filter to items we show (skip optional origin when flights disabled)
  const visibleItems = items.filter(
    (item) => item.isRequired || item.id !== 'origin' || isFlightsEnabled
  );

  const completedCount = visibleItems.filter((item) => item.isSet).length;
  const totalCount = visibleItems.length;
  const progress = totalCount > 0 ? completedCount / totalCount : 0;

  const handleClick = () => {
    console.log('[SetupProgressIndicator] Button clicked! Calling toggleSetupDrawer...');
    toggleSetupDrawer();
    console.log('[SetupProgressIndicator] toggleSetupDrawer called');
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(
        'flex items-center gap-2',
        'text-sm font-medium text-foreground',
        'hover:text-primary transition-colors',
        '-ml-1 px-1 py-1', // Expand tap target
        className
      )}
      aria-label={`Setup progress: ${completedCount} of ${totalCount} completed. Tap to ${isSetupDrawerOpen ? 'close' : 'open'} checklist.`}
      aria-expanded={isSetupDrawerOpen}
    >
      <ProgressRing progress={progress} />
      <span className="text-foreground">
        {completedCount}/{totalCount}
      </span>
      <span className="text-muted-foreground hidden xs:inline">Completed</span>
      <ChevronDown
        className={cn(
          'h-4 w-4 text-muted-foreground transition-transform duration-200',
          isSetupDrawerOpen && 'rotate-180'
        )}
      />
    </button>
  );
}

export const SetupProgressIndicator = memo(SetupProgressIndicatorInner);
