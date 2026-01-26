/**
 * ActivitiesSheet
 *
 * Module sheet for activity preferences.
 * Prerequisites: Destination (dates optional)
 * Includes toggle + category selection + pace.
 */

'use client';

import { AlertCircle, Ticket } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';

import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/utils';
import type { ActivitySettings } from '@/types/document';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ActivitiesSheetProps {
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

// Specialist activity categories (trigger specialist agents)
const SPECIALIST_CATEGORIES = [
  { value: 'diving', label: 'Diving', icon: '🤿', specialist: true },
  { value: 'hiking', label: 'Hiking', icon: '🥾', specialist: true },
  { value: 'skiing', label: 'Skiing', icon: '⛷️', specialist: true },
  { value: 'cycling', label: 'Cycling', icon: '🚴', specialist: true },
  { value: 'sailing', label: 'Sailing', icon: '⛵', specialist: true },
];

// General activity categories
const GENERAL_CATEGORIES = [
  { value: 'culture', label: 'Culture', icon: '🏛️' },
  { value: 'food', label: 'Food & Drink', icon: '🍽️' },
  { value: 'outdoors', label: 'Outdoors', icon: '🏔️' },
  { value: 'nightlife', label: 'Nightlife', icon: '🌙' },
  { value: 'shopping', label: 'Shopping', icon: '🛍️' },
  { value: 'wellness', label: 'Wellness', icon: '🧘' },
  { value: 'adventure', label: 'Adventure', icon: '🪂' },
  { value: 'family', label: 'Family', icon: '👨‍👩‍👧' },
];

// Skill level options
const SKILL_OPTIONS = [
  { value: 'beginner', label: 'Beginner', description: 'Easy activities, no experience needed' },
  { value: 'intermediate', label: 'Intermediate', description: 'Some experience helpful' },
  { value: 'advanced', label: 'Advanced', description: 'Challenging activities for experienced' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Gating Blocker Component
// ─────────────────────────────────────────────────────────────────────────────

interface GatingBlockerProps {
  hasDestination: boolean;
  onOpenDestination?: () => void;
  onClose: () => void;
}

function GatingBlocker({
  hasDestination,
  onOpenDestination,
  onClose,
}: GatingBlockerProps) {
  if (hasDestination) return null;

  return (
    <div className="mb-4 p-4 rounded-lg bg-amber-500/10 border border-amber-500/30">
      <div className="flex items-start gap-3">
        <AlertCircle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[var(--theme-text)]">
            To include activities, set a destination.
          </p>
          <div className="flex flex-wrap gap-2 mt-3">
            {onOpenDestination && (
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

  // Check if prerequisites met
  const prerequisitesMet = hasDestination;

  // Reset when opened
  useEffect(() => {
    if (open) {
      setLocalEnabled(enabled);
      setLocalCategories(settings.categories || []);
      setLocalSkillLevel(settings.skill_level || null);
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
    });
    toast('Activity preferences saved');
    onOpenChange(false);
  }, [localCategories, localSkillLevel, onSaveSettings, toast, onOpenChange]);

  // Toggle category
  const toggleCategory = useCallback((category: string) => {
    setLocalCategories((prev) =>
      prev.includes(category)
        ? prev.filter((c) => c !== category)
        : [...prev, category]
    );
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
            onOpenDestination={onOpenDestination}
            onClose={() => onOpenChange(false)}
          />
        )}

        {/* Include toggle */}
        <div className="flex items-center justify-between py-3 border-b border-[var(--theme-border)]">
          <div className="flex items-center gap-2">
            <Ticket className="h-5 w-5 text-[var(--theme-text)]" />
            <span className="text-sm font-medium text-[var(--theme-text)]">
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
            'space-y-5 transition-opacity',
            !localEnabled && 'opacity-40 pointer-events-none'
          )}
        >
          {/* Specialist Activities */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Specialist Activities
            </h3>
            <p className="text-xs text-[var(--theme-text-muted)] mb-3">
              Get expert planning with safety constraints
            </p>
            <div className="grid grid-cols-2 gap-2">
              {SPECIALIST_CATEGORIES.map((option) => {
                const isSelected = localCategories.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleCategory(option.value)}
                    className={cn(
                      'flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm',
                      'border transition-colors text-left',
                      isSelected
                        ? 'border-amber-500 bg-amber-500/10 text-amber-600 dark:text-amber-400'
                        : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-amber-500/50'
                    )}
                  >
                    <span>{option.icon}</span>
                    <span>{option.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* General Categories */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              General Categories
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {GENERAL_CATEGORIES.map((option) => {
                const isSelected = localCategories.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleCategory(option.value)}
                    className={cn(
                      'flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm',
                      'border transition-colors text-left',
                      isSelected
                        ? 'border-teal-500 bg-teal-500/10 text-teal-600 dark:text-teal-400'
                        : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] text-[var(--theme-text)] hover:border-teal-500/50'
                    )}
                  >
                    <span>{option.icon}</span>
                    <span>{option.label}</span>
                  </button>
                );
              })}
            </div>
            {localCategories.length === 0 && (
              <p className="text-xs text-[var(--theme-text-muted)] mt-2">
                No categories selected = mixed recommendations
              </p>
            )}
          </div>

          {/* Skill Level */}
          <div>
            <h3 className="text-xs font-medium text-[var(--theme-text-muted)] uppercase tracking-wide mb-2">
              Skill level
            </h3>
            <div className="space-y-2">
              {SKILL_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setLocalSkillLevel(option.value)}
                  className={cn(
                    'w-full flex flex-col items-start px-4 py-3 rounded-lg',
                    'border transition-colors text-left',
                    localSkillLevel === option.value
                      ? 'border-teal-500 bg-teal-500/10'
                      : 'border-[var(--theme-border)] bg-[var(--theme-overlay)] hover:border-teal-500/50'
                  )}
                >
                  <span
                    className={cn(
                      'text-sm font-medium',
                      localSkillLevel === option.value
                        ? 'text-teal-600 dark:text-teal-400'
                        : 'text-[var(--theme-text)]'
                    )}
                  >
                    {option.label}
                  </span>
                  <span className="text-xs text-[var(--theme-text-muted)]">
                    {option.description}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const ActivitiesSheet = memo(ActivitiesSheetInner);

export default ActivitiesSheet;
