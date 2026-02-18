/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivitiesSheet
 *
 * Module sheet for activity preferences.
 * Prerequisites: Destination (dates optional)
 * Includes toggle + category selection + pace.
 */

'use client';

import { Ticket } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { Stepper } from '@/components/ui/stepper';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { ActivitySettings } from '@/types/document';

import { BaseSheet } from './BaseSheet';
import { GatingBlocker } from './GatingBlocker';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface ActivitiesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Module state
  enabled: boolean;
  settings: ActivitySettings;
  // Prerequisites
  hasDestination: boolean;
  // Actions
  onToggle: (enabled: boolean) => void;
  onSaveSettings: (settings: ActivitySettings) => void;
  // Navigate to fix prerequisites
  onOpenDestination?: () => void;
}

// Activity categories — flat list, no visual distinction between tiers.
// Tier 1 (specialist) vs Tier 2 (experience) is a backend implementation detail.
const ALL_CATEGORIES = [
  { value: 'diving', label: 'Diving', icon: '🤿' },
  { value: 'hiking', label: 'Hiking', icon: '🥾' },
  { value: 'skiing', label: 'Skiing', icon: '⛷️' },
  { value: 'cycling', label: 'Cycling', icon: '🚴' },
  { value: 'sailing', label: 'Sailing', icon: '⛵' },
  { value: 'surfing', label: 'Surfing', icon: '🏄' },
  { value: 'cooking', label: 'Cooking', icon: '🍳' },
  { value: 'yoga', label: 'Yoga', icon: '🧘' },
  { value: 'temples', label: 'Temples', icon: '⛩️' },
  { value: 'nightlife', label: 'Nightlife', icon: '🎉' },
  { value: 'beach', label: 'Beach', icon: '🏖️' },
  { value: 'shopping', label: 'Shopping', icon: '🛍️' },
  { value: 'photography', label: 'Photography', icon: '📸' },
];

// Skill level options
const SKILL_OPTIONS = [
  { value: 'beginner', label: 'Beginner', description: 'Easy activities, no experience needed' },
  { value: 'intermediate', label: 'Intermediate', description: 'Some experience helpful' },
  { value: 'advanced', label: 'Advanced', description: 'Challenging activities for experienced' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function ActivitiesSheetInner({
  open,
  onOpenChange,
  enabled,
  settings,
  hasDestination,
  onToggle,
  onSaveSettings,
  onOpenDestination,
}: ActivitiesSheetProps) {
  const { toast } = useToast();
  const [localEnabled, setLocalEnabled] = useState(enabled);
  const [localCategories, setLocalCategories] = useState<string[]>(
    settings.categories || []
  );
  const [localSkillLevel, setLocalSkillLevel] = useState<string | null>(settings.skill_level || null);
  const [localDayPreferences, setLocalDayPreferences] = useState<Record<string, number>>(
    settings.day_preferences || {}
  );

  // Check if prerequisites met
  const prerequisitesMet = hasDestination;

  // Reset when opened
  useEffect(() => {
    if (open) {
      setLocalEnabled(enabled);
      setLocalCategories(settings.categories || []);
      setLocalSkillLevel(settings.skill_level || null);
      setLocalDayPreferences(settings.day_preferences || {});
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
      toast(checked ? 'Activities included' : 'Activities removed');
    },
    [prerequisitesMet, onToggle, toast]
  );

  // Handle save preferences
  const handleSave = useCallback(() => {
    onSaveSettings({
      categories: localCategories,
      skill_level: localSkillLevel,
      day_preferences: localDayPreferences,
    });
    toast('Activity preferences saved');
    onOpenChange(false);
  }, [localCategories, localSkillLevel, localDayPreferences, onSaveSettings, toast, onOpenChange]);

  // Toggle category
  const toggleCategory = useCallback((category: string) => {
    setLocalCategories((prev) =>
      prev.includes(category)
        ? prev.filter((c) => c !== category)
        : [...prev, category]
    );
  }, []);

  // Handle day preference changes
  const handleDayPreferenceChange = useCallback((category: string, days: number) => {
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
          featureLabel="activities"
          gates={[
            { label: 'Destination', met: hasDestination, onOpen: onOpenDestination },
          ]}
          onClose={() => onOpenChange(false)}
        />

        {/* Include toggle */}
        <div className="flex items-center justify-between py-3 border-b border-zinc-200 dark:border-white/10">
          <div className="flex items-center gap-2">
            <Ticket className="h-5 w-5 text-zinc-900 dark:text-white" />
            <span className="text-sm font-medium text-zinc-900 dark:text-white">
              Include activities
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
          {/* Activity Categories — single flat grid */}
          <div>
            <div className="grid grid-cols-2 gap-2">
              {ALL_CATEGORIES.map((option) => {
                const isSelected = localCategories.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleCategory(option.value)}
                    className={cn(
                      'flex items-center gap-2 px-3 py-3 rounded-lg text-sm font-medium',
                      'transition-all duration-150 text-left',
                      isSelected
                        ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                    )}
                  >
                    <span>{option.icon}</span>
                    <span>{option.label}</span>
                  </button>
                );
              })}
            </div>
            {localCategories.length === 0 && (
              <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-2">
                No categories selected = mixed recommendations
              </p>
            )}
          </div>

          {/* Day preferences — only when categories selected */}
          {localCategories.length > 0 && (
            <div>
              <h3 className={cn(DS.text.label, 'mb-3')}>
                Days per activity
              </h3>
              <p className="text-xs text-zinc-500 dark:text-zinc-500 mb-2">
                Set 0 for no preference
              </p>
              <div className="space-y-1">
                {localCategories.map((catValue) => {
                  const catDef = ALL_CATEGORIES.find(c => c.value === catValue);
                  return (
                    <div key={catValue} className="flex items-center justify-between py-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{catDef?.icon || '🏷️'}</span>
                        <span className="text-sm font-medium text-zinc-900 dark:text-white">
                          {catDef?.label || catValue}
                        </span>
                      </div>
                      <Stepper
                        value={localDayPreferences[catValue] || 0}
                        min={0}
                        max={7}
                        size="sm"
                        onChange={(val) => handleDayPreferenceChange(catValue, val)}
                        label={`${catDef?.label || catValue} days`}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Skill Level */}
          <div>
            <h3 className={cn(DS.text.label, 'mb-3')}>
              Skill level
            </h3>
            <div className="space-y-2">
              {SKILL_OPTIONS.map((option) => {
                const isSelected = localSkillLevel === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setLocalSkillLevel(option.value)}
                    className={cn(
                      'w-full flex flex-col items-start px-4 py-3.5 rounded-lg',
                      'transition-all duration-150 text-left',
                      isSelected
                        // Selected: Strong ring for emphasis
                        ? 'bg-zinc-900 text-white border-2 border-transparent shadow-md dark:bg-white dark:text-black dark:border-transparent'
                        // Inactive: Glass Fill
                        : cn(
                            'bg-white border-2 border-zinc-200',
                            'hover:border-zinc-900 hover:bg-zinc-50',
                            // Dark: Glass substance
                            'dark:bg-white/5 dark:border-2 dark:border-white/15',
                            'dark:hover:bg-white/10 dark:hover:border-white/40'
                          )
                    )}
                  >
                    <span
                      className={cn(
                        'text-sm font-semibold',
                        isSelected
                          ? 'text-white dark:text-black'
                          : 'text-zinc-600 dark:text-zinc-400'
                      )}
                    >
                      {option.label}
                    </span>
                    <span className="text-xs text-zinc-500 dark:text-zinc-500">
                      {option.description}
                    </span>
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

export const ActivitiesSheet = memo(ActivitiesSheetInner);

export default ActivitiesSheet;
