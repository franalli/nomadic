/**
 * StaysSheet
 *
 * Module sheet for accommodation (hotel/stays) preferences.
 * Prerequisites: Destination + Dates
 * Includes toggle + preferences.
 *
 * Note: Uses "Stays" in UI copy per spec, but internal state uses "hotels".
 */

'use client';

import { AlertCircle, Hotel } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/utils';
import type { HotelSettings } from '@/types/document';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface StaysSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Module state
  enabled: boolean;
  settings: HotelSettings;
  // Prerequisites
  hasDestination: boolean;
  hasDates: boolean;
  // Actions
  onToggle: (enabled: boolean) => void;
  onSaveSettings: (settings: HotelSettings) => void;
  // Navigate to fix prerequisites
  onOpenDestination?: () => void;
  onOpenDates?: () => void;
}

// Star rating options
const STAR_OPTIONS = [
  { value: 0, label: 'Any' },
  { value: 3, label: '3★+' },
  { value: 4, label: '4★+' },
  { value: 5, label: '5★' },
];

// Amenity options
const AMENITY_OPTIONS = [
  { value: 'wifi', label: 'WiFi' },
  { value: 'pool', label: 'Pool' },
  { value: 'parking', label: 'Parking' },
  { value: 'gym', label: 'Gym' },
  { value: 'spa', label: 'Spa' },
  { value: 'breakfast', label: 'Breakfast' },
  { value: 'pet_friendly', label: 'Pet friendly' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Gating Blocker Component
// ─────────────────────────────────────────────────────────────────────────────

interface GatingBlockerProps {
  hasDestination: boolean;
  hasDates: boolean;
  onOpenDestination?: () => void;
  onOpenDates?: () => void;
  onClose: () => void;
}

function GatingBlocker({
  hasDestination,
  hasDates,
  onOpenDestination,
  onOpenDates,
  onClose,
}: GatingBlockerProps) {
  const missing: string[] = [];
  if (!hasDestination) missing.push('Destination');
  if (!hasDates) missing.push('Dates');

  return (
    <div className="mb-4 p-4 rounded-lg bg-amber-500/10 border border-amber-500/30">
      <div className="flex items-start gap-3">
        <AlertCircle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[var(--theme-text)]">
            To include stays, set {missing.join(' + ')}.
          </p>
          <div className="flex flex-wrap gap-2 mt-3">
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

function StaysSheetInner({
  open,
  onOpenChange,
  enabled,
  settings,
  hasDestination,
  hasDates,
  onToggle,
  onSaveSettings,
  onOpenDestination,
  onOpenDates,
}: StaysSheetProps) {
  const { toast } = useToast();
  const [localEnabled, setLocalEnabled] = useState(enabled);
  const [localSettings, setLocalSettings] = useState<HotelSettings>(settings);

  // Check if prerequisites met
  const prerequisitesMet = hasDestination && hasDates;

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
      if (checked && !prerequisitesMet) {
        return;
      }
      setLocalEnabled(checked);
      onToggle(checked);
      toast(checked ? 'Stays included' : 'Stays removed');
    },
    [prerequisitesMet, onToggle, toast]
  );

  // Handle save preferences
  const handleSave = useCallback(() => {
    onSaveSettings(localSettings);
    toast('Stay preferences saved');
    onOpenChange(false);
  }, [localSettings, onSaveSettings, toast, onOpenChange]);

  // Update star rating
  const handleStarChange = useCallback((minStars: number) => {
    setLocalSettings((prev) => ({ ...prev, min_stars: minStars }));
  }, []);

  // Toggle amenity
  const toggleAmenity = useCallback((amenity: string) => {
    setLocalSettings((prev) => {
      const current = prev.amenities || [];
      const newAmenities = current.includes(amenity)
        ? current.filter((a) => a !== amenity)
        : [...current, amenity];
      return { ...prev, amenities: newAmenities };
    });
  }, []);

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Stays"
      hint="Configure accommodation preferences"
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
            hasDestination={hasDestination}
            hasDates={hasDates}
            onOpenDestination={onOpenDestination}
            onOpenDates={onOpenDates}
            onClose={() => onOpenChange(false)}
          />
        )}

        {/* Include toggle */}
        <div className="flex items-center justify-between py-3 border-b border-[var(--theme-border)]">
          <div className="flex items-center gap-2">
            <Hotel className="h-5 w-5 text-[var(--theme-text)]" />
            <span className="text-sm font-medium text-[var(--theme-text)]">
              Include stays
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
          {/* Star rating */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Minimum stars
            </h3>
            <div className="flex gap-2">
              {STAR_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => handleStarChange(option.value)}
                  className={cn(
                    'flex-1 px-3 py-2 rounded-lg text-sm',
                    'border transition-colors',
                    localSettings.min_stars === option.value
                      ? 'border-teal-500 bg-teal-500/10 text-teal-600 dark:text-teal-400'
                      : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-teal-500/50'
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          {/* Amenities */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Preferred amenities
            </h3>
            <div className="flex flex-wrap gap-2">
              {AMENITY_OPTIONS.map((option) => {
                const isSelected = (localSettings.amenities || []).includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleAmenity(option.value)}
                    className={cn(
                      'px-3 py-1.5 rounded-full text-sm',
                      'border transition-colors',
                      isSelected
                        ? 'border-teal-500 bg-teal-500/10 text-teal-600 dark:text-teal-400'
                        : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-teal-500/50'
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

export const StaysSheet = memo(StaysSheetInner);

export default StaysSheet;
