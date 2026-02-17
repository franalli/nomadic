/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * FlightsSheet
 *
 * Module sheet for flight preferences.
 * Prerequisites: Origin + Destination + Dates
 * Includes toggle + preferences.
 */

'use client';

import { Plane } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { FlightSettings } from '@/types/document';

import { BaseSheet } from './BaseSheet';
import { GatingBlocker } from './GatingBlocker';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface FlightsSheetProps {
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

// Cabin class options
const CABIN_OPTIONS: { value: FlightSettings['cabin_class']; label: string }[] = [
  { value: 'economy', label: 'Economy' },
  { value: 'premium_economy', label: 'Premium' },
  { value: 'business', label: 'Business' },
  { value: 'first', label: 'First' },
];

// Stops options
const STOPS_OPTIONS = [
  { value: 'any', label: 'Any stops', directOnly: false },
  { value: 'nonstop', label: 'Nonstop only', directOnly: true },
];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

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
        <div className="flex gap-3">
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
            !localEnabled && 'opacity-40 pointer-events-none'
          )}
        >
          {/* Trip type */}
          <div>
            <h3 className={cn(DS.text.label, 'mb-3')}>
              Trip type
            </h3>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => updateSetting('round_trip', true)}
                className={cn(
                  'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
                  'transition-all duration-150',
                  localSettings.round_trip
                    // Selected: Solid Black (maximum contrast)
                    ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                    // Tactile: Crisp border, snap-to-black hover
                    // Inactive: Glass Fill - visible buttons
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          // Dark: Glass substance
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                )}
              >
                Round trip
              </button>
              <button
                type="button"
                onClick={() => updateSetting('round_trip', false)}
                className={cn(
                  'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
                  'transition-all duration-150',
                  !localSettings.round_trip
                    ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                    // Inactive: Glass Fill - visible buttons
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          // Dark: Glass substance
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                )}
              >
                One-way
              </button>
            </div>
          </div>

          {/* Cabin class */}
          <div>
            <h3 className={cn(DS.text.label, 'mb-3')}>
              Cabin class
            </h3>
            <div className="flex flex-wrap gap-2">
              {CABIN_OPTIONS.map((option) => {
                const isSelected = localSettings.cabin_class === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => updateSetting('cabin_class', option.value)}
                    className={cn(
                      'px-4 py-2.5 rounded-lg text-sm font-medium',
                      'transition-all duration-150',
                      isSelected
                        // Selected: Solid Black (maximum contrast)
                        ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                        // Tactile: Crisp border, snap-to-black hover
                        // Inactive: Glass Fill - visible buttons
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          // Dark: Glass substance
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                    )}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Stops */}
          <div>
            <h3 className={cn(DS.text.label, 'mb-3')}>
              Stops
            </h3>
            <div className="flex gap-2">
              {STOPS_OPTIONS.map((option) => {
                const isSelected = localSettings.direct_only === option.directOnly;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => updateSetting('direct_only', option.directOnly)}
                    className={cn(
                      'flex-1 px-3 py-2.5 rounded-lg text-sm font-medium',
                      'transition-all duration-150',
                      isSelected
                        // Selected: Solid Black (maximum contrast)
                        ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                        // Tactile: Crisp border, snap-to-black hover
                        // Inactive: Glass Fill - visible buttons
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          // Dark: Glass substance
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                    )}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const FlightsSheet = memo(FlightsSheetInner);

export default FlightsSheet;
