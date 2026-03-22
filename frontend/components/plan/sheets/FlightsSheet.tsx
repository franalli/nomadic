'use client';

import { Plane } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { FlightSettings } from '@/types/document';

import { BaseSheet } from './BaseSheet';
import { CabinClassSelector, StopsSelector, TripTypeSelector } from './FlightsSheetParts';
import { GatingBlocker } from './GatingBlocker';

interface FlightsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Module state
  enabled: boolean;
  settings: FlightSettings;
  // Prerequisites
  hasOrigin: boolean;
  hasDestination: boolean;
  hasDates: boolean;
  // Actions
  onToggle: (enabled: boolean) => void;
  onSaveSettings: (settings: FlightSettings) => void;
  // Navigate to fix prerequisites
  onOpenOrigin?: () => void;
  onOpenDestination?: () => void;
  onOpenDates?: () => void;
}

function FlightsSheetInner({
  open,
  onOpenChange,
  enabled,
  settings,
  hasOrigin,
  hasDestination,
  hasDates,
  onToggle,
  onSaveSettings,
  onOpenOrigin,
  onOpenDestination,
  onOpenDates,
}: FlightsSheetProps) {
  const { toast } = useToast();
  const [localEnabled, setLocalEnabled] = useState(enabled);
  const [localSettings, setLocalSettings] = useState<FlightSettings>(settings);

  // Check if prerequisites met
  const prerequisitesMet = hasOrigin && hasDestination && hasDates;

  // Reset when opened
  useEffect(() => {
    if (open) {
      setLocalEnabled(enabled);
      setLocalSettings(settings);
    }
  }, [open, enabled, settings]);

  // Handle toggle (commits immediately)
  const handleToggle = useCallback(
    (checked: boolean) => {
      // Can only enable if prerequisites met
      if (checked && !prerequisitesMet) {
        return;
      }
      setLocalEnabled(checked);
      onToggle(checked);
      toast(checked ? 'Flights included' : 'Flights removed');
    },
    [prerequisitesMet, onToggle, toast]
  );

  // Handle save preferences
  const handleSave = useCallback(() => {
    onSaveSettings(localSettings);
    toast('Flight preferences saved');
    onOpenChange(false);
  }, [localSettings, onSaveSettings, toast, onOpenChange]);

  // Update local setting
  const updateSetting = useCallback(
    <K extends keyof FlightSettings>(key: K, value: FlightSettings[K]) => {
      setLocalSettings((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Flights"
      hint="Configure flight search preferences"
      footer={
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className={cn(
              'flex-1 px-4 py-2.5 rounded-xl text-sm font-medium',
              'text-zinc-500 dark:text-zinc-500',
              'hover:text-zinc-900 hover:bg-zinc-100',
              'dark:hover:text-white dark:hover:bg-white/5',
              'transition-colors'
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!localEnabled}
            className={cn(
              localEnabled ? DS.actions.primary : DS.actions.primaryDisabled,
              'flex-1 px-4 py-2.5 font-semibold'
            )}
          >
            Save
          </button>
        </div>
      }
    >
      <div className="space-y-6">
        {/* Gating blocker */}
        <GatingBlocker
          featureLabel="flights"
          gates={[
            { label: 'Origin', met: hasOrigin, onOpen: onOpenOrigin },
            { label: 'Destination', met: hasDestination, onOpen: onOpenDestination },
            { label: 'Dates', met: hasDates, onOpen: onOpenDates },
          ]}
          onClose={() => onOpenChange(false)}
        />

        {/* Include toggle */}
        <div className="flex items-center justify-between py-3 border-b border-zinc-200 dark:border-white/10">
          <div className="flex items-center gap-2">
            <Plane className="h-5 w-5 text-zinc-900 dark:text-white" />
            <span className="text-sm font-medium text-zinc-900 dark:text-white">
              Include flights
            </span>
          </div>
          <Switch
            checked={localEnabled}
            onCheckedChange={handleToggle}
            disabled={!prerequisitesMet && !localEnabled}
          />
        </div>

        {/* Preferences (disabled when toggle off) */}
        <div
          className={cn(
            'space-y-6 transition-opacity',
            !localEnabled && 'opacity-50 cursor-not-allowed pointer-events-none'
          )}
        >
          {/* Trip type */}
          <TripTypeSelector
            roundTrip={localSettings.round_trip}
            onChange={(v) => updateSetting('round_trip', v)}
          />

          {/* Cabin class */}
          <CabinClassSelector
            cabinClass={localSettings.cabin_class}
            onChange={(v) => updateSetting('cabin_class', v)}
          />

          {/* Stops */}
          <StopsSelector
            directOnly={localSettings.direct_only}
            onChange={(v) => updateSetting('direct_only', v)}
          />
        </div>
      </div>
    </BaseSheet>
  );
}

export const FlightsSheet = memo(FlightsSheetInner);

export default FlightsSheet;
