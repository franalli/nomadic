'use client';
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


import { Hotel } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { HotelSettings } from '@/types/document';

import { BaseSheet } from './BaseSheet';
import { GatingBlocker } from './GatingBlocker';
import { AmenitiesSection, StarRatingSection } from './StaysSheetParts';

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
            !localEnabled && 'opacity-50 cursor-not-allowed pointer-events-none'
          )}
        >
          <StarRatingSection
            minStars={localSettings.min_stars ?? 0}
            onChange={handleStarChange}
          />
          <AmenitiesSection
            amenities={localSettings.amenities || []}
            onToggle={toggleAmenity}
          />
        </div>
      </div>
    </BaseSheet>
  );
}

export const StaysSheet = memo(StaysSheetInner);

export default StaysSheet;
