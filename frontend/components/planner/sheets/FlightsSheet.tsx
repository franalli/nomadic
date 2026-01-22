/**
 * FlightsSheet
 *
 * Module sheet for flight preferences.
 * Prerequisites: Origin + Destination + Dates
 * Includes toggle + preferences.
 */

'use client';

import { AlertCircle, Plane } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { BaseSheet } from './BaseSheet';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import type { FlightSettings } from '@/types/document';

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
// Gating Blocker Component
// ─────────────────────────────────────────────────────────────────────────────

interface GatingBlockerProps {
  hasOrigin: boolean;
  hasDestination: boolean;
  hasDates: boolean;
  onOpenOrigin?: () => void;
  onOpenDestination?: () => void;
  onOpenDates?: () => void;
  onClose: () => void;
}

function GatingBlocker({
  hasOrigin,
  hasDestination,
  hasDates,
  onOpenOrigin,
  onOpenDestination,
  onOpenDates,
  onClose,
}: GatingBlockerProps) {
  const missing: string[] = [];
  if (!hasOrigin) missing.push('Origin');
  if (!hasDestination) missing.push('Destination');
  if (!hasDates) missing.push('Dates');

  return (
    <div className="mb-4 p-4 rounded-lg bg-amber-500/10 border border-amber-500/30">
      <div className="flex items-start gap-3">
        <AlertCircle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[var(--theme-text)]">
            To include flights, set {missing.join(' + ')}.
          </p>
          <div className="flex flex-wrap gap-2 mt-3">
            {!hasOrigin && onOpenOrigin && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  setTimeout(onOpenOrigin, 150);
                }}
                className={cn(
                  'px-3 py-1.5 rounded-full text-sm font-medium',
                  'bg-amber-500 text-white',
                  'hover:bg-amber-600 transition-colors'
                )}
              >
                Set origin
              </button>
            )}
            {!hasDestination && onOpenDestination && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  setTimeout(onOpenDestination, 150);
                }}
                className={cn(
                  'px-3 py-1.5 rounded-full text-sm font-medium',
                  'bg-amber-500 text-white',
                  'hover:bg-amber-600 transition-colors'
                )}
              >
                Set destination
              </button>
            )}
            {!hasDates && onOpenDates && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  setTimeout(onOpenDates, 150);
                }}
                className={cn(
                  'px-3 py-1.5 rounded-full text-sm font-medium',
                  'bg-amber-500 text-white',
                  'hover:bg-amber-600 transition-colors'
                )}
              >
                Set dates
              </button>
            )}
          </div>
          <p className="text-xs text-[var(--theme-text-muted)] mt-2">
            You can keep defaults for everything else.
          </p>
        </div>
      </div>
    </div>
  );
}

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
              'flex-1 px-4 py-2.5 rounded-lg text-sm font-medium',
              'border border-[var(--theme-border)]',
              'text-[var(--theme-text-muted)]',
              'hover:bg-[var(--theme-overlay)]',
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
              'flex-1 px-4 py-2.5 rounded-lg text-sm font-medium',
              'transition-colors',
              localEnabled
                ? 'bg-amber-500 text-white hover:bg-amber-600'
                : 'bg-zinc-200 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-600 cursor-not-allowed'
            )}
          >
            Save
          </button>
        </div>
      }
    >
      <div className="space-y-5">
        {/* Gating blocker */}
        {!prerequisitesMet && (
          <GatingBlocker
            hasOrigin={hasOrigin}
            hasDestination={hasDestination}
            hasDates={hasDates}
            onOpenOrigin={onOpenOrigin}
            onOpenDestination={onOpenDestination}
            onOpenDates={onOpenDates}
            onClose={() => onOpenChange(false)}
          />
        )}

        {/* Include toggle */}
        <div className="flex items-center justify-between py-3 border-b border-[var(--theme-border)]">
          <div className="flex items-center gap-2">
            <Plane className="h-5 w-5 text-[var(--theme-text)]" />
            <span className="text-sm font-medium text-[var(--theme-text)]">
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
            'space-y-5 transition-opacity',
            !localEnabled && 'opacity-40 pointer-events-none'
          )}
        >
          {/* Trip type */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Trip type
            </h3>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => updateSetting('round_trip', true)}
                className={cn(
                  'flex-1 px-3 py-2 rounded-lg text-sm',
                  'border transition-colors',
                  localSettings.round_trip
                    ? 'border-teal-500 bg-teal-500/10 text-teal-600 dark:text-teal-400'
                    : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-teal-500/50'
                )}
              >
                Round trip
              </button>
              <button
                type="button"
                onClick={() => updateSetting('round_trip', false)}
                className={cn(
                  'flex-1 px-3 py-2 rounded-lg text-sm',
                  'border transition-colors',
                  !localSettings.round_trip
                    ? 'border-teal-500 bg-teal-500/10 text-teal-600 dark:text-teal-400'
                    : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-teal-500/50'
                )}
              >
                One-way
              </button>
            </div>
          </div>

          {/* Cabin class */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Cabin class
            </h3>
            <div className="flex flex-wrap gap-2">
              {CABIN_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => updateSetting('cabin_class', option.value)}
                  className={cn(
                    'px-3 py-1.5 rounded-full text-sm',
                    'border transition-colors',
                    localSettings.cabin_class === option.value
                      ? 'border-teal-500 bg-teal-500/10 text-teal-600 dark:text-teal-400'
                      : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-teal-500/50'
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          {/* Stops */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Stops
            </h3>
            <div className="flex gap-2">
              {STOPS_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => updateSetting('direct_only', option.directOnly)}
                  className={cn(
                    'flex-1 px-3 py-2 rounded-lg text-sm',
                    'border transition-colors',
                    localSettings.direct_only === option.directOnly
                      ? 'border-teal-500 bg-teal-500/10 text-teal-600 dark:text-teal-400'
                      : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-teal-500/50'
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const FlightsSheet = memo(FlightsSheetInner);

export default FlightsSheet;
