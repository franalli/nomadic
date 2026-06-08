'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivitiesSheet — Module sheet for activity preferences.
 * Prerequisites: Destination (dates optional). Includes toggle + category selection + pace.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useToast } from '@/components/ui/toast';
import { useDocumentStore } from '@/state/documentStore';
import type { ActivitySettings } from '@/types/document';

import { ActivitiesSheetContent } from './ActivitiesSheetContent';
import {
  inferCategoriesFromDayCards,
  inferDayPreferencesFromDayCards,
  inferUnrepresentableCategoriesFromDayCards,
} from './activitiesSheetHelpers';
import {
  ActivitiesSheetFooter,
  buildSavePayload,
  deriveEffectiveInitialCategories,
  deriveEffectiveInitialDayPreferences,
  normalizeSettingCategories as normalizeCategories,
  normalizeSettingDayPreferences as normalizeDayPrefs,
} from './ActivitiesSheetParts';
import { BaseSheet } from './BaseSheet';

interface ActivitiesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Module state
  enabled: boolean;
  settings: ActivitySettings;
  /** True when activity_settings has been explicitly saved at least once.
   *  When false, inferred categories from day cards are shown as initial selection. */
  hasExplicitSettings?: boolean;
  // Prerequisites
  hasDestination: boolean;
  // Actions
  onToggle: (enabled: boolean) => void;
  onSaveSettings: (settings: ActivitySettings) => void;
  // Navigate to fix prerequisites
  onOpenDestination?: () => void;
}

function ActivitiesSheetInner({
  open,
  onOpenChange,
  enabled,
  settings,
  hasExplicitSettings = false,
  hasDestination,
  onToggle,
  onSaveSettings,
  onOpenDestination,
}: ActivitiesSheetProps) {
  const { toast } = useToast();
  const dayCards = useDocumentStore(useShallow((s) => s.document?.day_cards));
  const inferredCategories = useMemo(() => inferCategoriesFromDayCards(dayCards), [dayCards]);
  const inferredDayPreferences = useMemo(() => inferDayPreferencesFromDayCards(dayCards), [dayCards]);
  // Itinerary-present categories the modal can't render as chips -- preserved on
  // Save so a no-op save never silently drops them (see buildSavePayload).
  const preservedCategories = useMemo(
    () => inferUnrepresentableCategoriesFromDayCards(dayCards),
    [dayCards]
  );
  const normalizedSettingCategories = useMemo(
    () => normalizeCategories(settings.categories),
    [settings.categories]
  );
  const normalizedSettingDayPreferences = useMemo(
    () => normalizeDayPrefs(settings.day_preferences),
    [settings.day_preferences]
  );
  const hasItinerary = (dayCards?.length ?? 0) > 0;
  const effectiveInitialCategories = useMemo(
    () => deriveEffectiveInitialCategories(normalizedSettingCategories, hasExplicitSettings, inferredCategories),
    [normalizedSettingCategories, hasExplicitSettings, inferredCategories]
  );
  const effectiveInitialDayPreferences = useMemo(
    () => deriveEffectiveInitialDayPreferences(hasItinerary, effectiveInitialCategories, inferredDayPreferences, normalizedSettingDayPreferences),
    [hasItinerary, effectiveInitialCategories, inferredDayPreferences, normalizedSettingDayPreferences]
  );
  const [localEnabled, setLocalEnabled] = useState(enabled);
  const [localCategories, setLocalCategories] = useState<string[]>(
    effectiveInitialCategories
  );
  const [localDayPreferences, setLocalDayPreferences] = useState<Record<string, number>>(
    effectiveInitialDayPreferences
  );
  const [localPace, setLocalPace] = useState<number | null>(
    settings.activities_per_day ?? 1
  );
  // Track which categories had their day-preference stepper manually adjusted.
  // Only these entries are sent in day_preferences on save — inferred defaults
  // and seed values (toggleCategory seeds with 1) are display-only.
  const [userAdjustedCategories, setUserAdjustedCategories] = useState<Set<string>>(new Set());
  const wasOpenRef = useRef(false);

  // Check if prerequisites met
  const prerequisitesMet = hasDestination;

  // Reset when opened
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setLocalEnabled(enabled);
      setLocalCategories(effectiveInitialCategories);
      setLocalDayPreferences(effectiveInitialDayPreferences);
      setLocalPace(settings.activities_per_day ?? 1);
      setUserAdjustedCategories(new Set());
    }
    wasOpenRef.current = open;
  }, [open, enabled, effectiveInitialCategories, effectiveInitialDayPreferences, settings.activities_per_day]);

  // Handle toggle (commits immediately)
  const handleToggle = useCallback(
    (checked: boolean) => {
      if (checked && !prerequisitesMet) {
        return;
      }
      setLocalEnabled(checked);
      onToggle(checked);
      toast(checked ? 'Activities included' : 'Activities removed');
    },
    [prerequisitesMet, onToggle, toast]
  );

  // Handle save preferences
  const handleSave = useCallback(() => {
    onSaveSettings(
      buildSavePayload(
        localCategories,
        localDayPreferences,
        localPace,
        userAdjustedCategories,
        preservedCategories
      )
    );
    toast('Activity preferences saved');
    onOpenChange(false);
  }, [localCategories, localDayPreferences, localPace, userAdjustedCategories, preservedCategories, onSaveSettings, toast, onOpenChange]);

  // Toggle category — when adding, seed day_preferences with a default of 1
  const toggleCategory = useCallback((category: string) => {
    setLocalCategories((prev) => {
      if (prev.includes(category)) {
        return prev.filter((c) => c !== category);
      }
      // Seed day_preferences so the stepper doesn't show a contradictory "0"
      setLocalDayPreferences(dp =>
        category in dp ? dp : { ...dp, [category]: 1 }
      );
      return [...prev, category];
    });
  }, []);

  // Handle day preference changes
  const handleDayPreferenceChange = useCallback((category: string, days: number) => {
    setUserAdjustedCategories(prev => {
      if (prev.has(category)) return prev;
      return new Set([...prev, category]);
    });
    setLocalDayPreferences(prev => {
      if (days === 0) {
        const rest = { ...prev };
        delete rest[category];
        return rest; // Remove key when 0 (no preference)
      }
      return { ...prev, [category]: days };
    });
  }, []);

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Activities"
      hint="Configure activity preferences"
      footer={
        <ActivitiesSheetFooter
          localEnabled={localEnabled}
          onCancel={() => onOpenChange(false)}
          onSave={handleSave}
        />
      }
    >
      <ActivitiesSheetContent
        localEnabled={localEnabled}
        localCategories={localCategories}
        localDayPreferences={localDayPreferences}
        localPace={localPace}
        prerequisitesMet={prerequisitesMet}
        hasDestination={hasDestination}
        onToggle={handleToggle}
        onSetLocalPace={setLocalPace}
        onToggleCategory={toggleCategory}
        onDayPreferenceChange={handleDayPreferenceChange}
        onOpenDestination={onOpenDestination}
        onOpenChange={onOpenChange}
      />
    </BaseSheet>
  );
}

export const ActivitiesSheet = memo(ActivitiesSheetInner);

export default ActivitiesSheet;
