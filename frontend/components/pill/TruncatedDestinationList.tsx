'use client';

import { Loader2 } from 'lucide-react';
import { Fragment, memo, useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

import { LocationBadge } from './LocationBadge';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface TruncatedDestinationListProps {
  destinations: string[];
  maxVisible?: number;
  selectedBadge: 'origin' | number | null;
  onSelectBadge: (key: 'origin' | number | null) => void;
  onRemoveDestination: (index: number) => void;
  destinationInput: string;
  setDestinationInput: (v: string) => void;
  onAddDestination: (destination: string) => void;
  hasDestination: boolean;
  pendingDestination: string | null;
  /** @deprecated Multi-city feature removed */
  multiCityIntent?: 'multi_city' | 'separate' | null;
  /** @deprecated Multi-city feature removed */
  onToggleMultiCity?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// TruncatedDestinationList Component
// ─────────────────────────────────────────────────────────────────────────────

function TruncatedDestinationListInner({
  destinations,
  maxVisible = 2,
  selectedBadge,
  onSelectBadge,
  onRemoveDestination,
  destinationInput,
  setDestinationInput,
  onAddDestination,
  hasDestination,
  pendingDestination,
  multiCityIntent: _multiCityIntent,
  onToggleMultiCity: _onToggleMultiCity,
}: TruncatedDestinationListProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Show simple "and" separator between destinations
  const showSeparator = destinations.length >= 2;

  const visibleDestinations = destinations.slice(0, maxVisible);
  const hiddenDestinations = destinations.slice(maxVisible);
  const hiddenCount = hiddenDestinations.length;

  return (
    <>
      {/* Visible destinations with separators */}
      {visibleDestinations.map((dest, idx) => (
        <Fragment key={`dest-group-${idx}`}>
          <LocationBadge
            type="destination"
            index={idx}
            value={dest}
            isSelected={selectedBadge === idx}
            onSelect={onSelectBadge}
            onRemove={() => onRemoveDestination(idx)}
          />
          {/* Show separator between visible destinations */}
          {showSeparator && idx < visibleDestinations.length - 1 && (
            <span className="text-[10px] font-medium text-muted-foreground self-center px-1">
              and
            </span>
          )}
        </Fragment>
      ))}

      {/* "+X more" badge with Popover */}
      {hiddenCount > 0 && (
        <Popover open={isExpanded} onOpenChange={setIsExpanded}>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="inline-flex items-center gap-0.5 text-xs font-semibold text-muted-foreground hover:text-foreground rounded-full px-1.5 py-0.5 hover:bg-gradient-to-b hover:from-muted/70 hover:to-muted/40 transition-all duration-150"
            >
              +{hiddenCount} more
            </button>
          </PopoverTrigger>
          <PopoverContent
            className="w-auto max-w-[300px] p-2 rounded-xl"
            align="start"
            sideOffset={8}
          >
            <div className="flex flex-wrap gap-2">
              {hiddenDestinations.map((dest, idx) => {
                const actualIndex = maxVisible + idx;
                return (
                  <LocationBadge
                    key={`dest-hidden-${actualIndex}`}
                    type="destination"
                    index={actualIndex}
                    value={dest}
                    isSelected={selectedBadge === actualIndex}
                    onSelect={onSelectBadge}
                    onRemove={() => onRemoveDestination(actualIndex)}
                  />
                );
              })}
            </div>
          </PopoverContent>
        </Popover>
      )}

      {/* Pending destination loader */}
      {pendingDestination && (
        <div className="inline-flex items-center gap-1.5 animate-pulse">
          <Loader2 className="h-3 w-3 text-accent animate-spin" />
          <span className="text-xs font-semibold text-accent/80">
            {pendingDestination}
          </span>
        </div>
      )}

      {/* Input form */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (destinationInput.trim()) {
            onAddDestination(destinationInput);
            setDestinationInput('');
          }
        }}
        className="flex-1 min-w-[60px]"
      >
        <input
          type="text"
          value={destinationInput}
          onChange={(e) => setDestinationInput(e.target.value)}
          placeholder={hasDestination ? 'Add' : 'Enter city or region'}
          className="w-full bg-transparent border-none text-sm placeholder:text-muted-foreground/50 focus:outline-none"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              if (destinationInput.trim()) {
                onAddDestination(destinationInput);
                setDestinationInput('');
              }
            }
          }}
        />
      </form>
    </>
  );
}

export const TruncatedDestinationList = memo(TruncatedDestinationListInner);
