/* eslint no-unused-vars: ["error", { "args": "none" }] */
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

import { Hotel } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { HotelSettings } from '@/types/document';

import { BaseSheet } from './BaseSheet';
import { GatingBlocker } from './GatingBlocker';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface StaysSheetProps {
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
          featureLabel="stays"
          gates={[
            { label: 'Destination', met: hasDestination, onOpen: onOpenDestination },
            { label: 'Dates', met: hasDates, onOpen: onOpenDates },
          ]}
          onClose={() => onOpenChange(false)}
        />

        {/* Include toggle */}
        <div className="flex items-center justify-between py-3 border-b border-zinc-200 dark:border-white/10">
          <div className="flex items-center gap-2">
            <Hotel className="h-5 w-5 text-zinc-900 dark:text-white" />
            <span className="text-sm font-medium text-zinc-900 dark:text-white">
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
            'space-y-6 transition-opacity',
            !localEnabled && 'opacity-50 pointer-events-none'
          )}
        >
          {/* Star rating */}
          <div>
            <h3 className={cn(DS.text.label, 'mb-3')}>
              Minimum stars
            </h3>
            <div className="flex gap-2">
              {STAR_OPTIONS.map((option) => {
                const isSelected = localSettings.min_stars === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleStarChange(option.value)}
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

          {/* Amenities */}
          <div>
            <h3 className={cn(DS.text.label, 'mb-3')}>
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
        </div>
      </div>
    </BaseSheet>
  );
}

export const StaysSheet = memo(StaysSheetInner);

export default StaysSheet;
