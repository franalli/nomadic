'use client';

import { Ticket } from 'lucide-react';

import { Stepper } from '@/components/ui/stepper';
import { Switch } from '@/components/ui/switch';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import { ALL_CATEGORIES, PACE_OPTIONS } from './activitiesSheetHelpers';
import { GatingBlocker } from './GatingBlocker';

// Re-export so existing consumers keep working
export { ALL_CATEGORIES } from './activitiesSheetHelpers';

export interface ActivitiesSheetContentProps {
  localEnabled: boolean;
  localCategories: string[];
  localDayPreferences: Record<string, number>;
  localPace: number | null;
  prerequisitesMet: boolean;
  hasDestination: boolean;
  onToggle: (checked: boolean) => void;
  onSetLocalPace: (pace: number | null) => void;
  onToggleCategory: (category: string) => void;
  onDayPreferenceChange: (category: string, days: number) => void;
  onOpenDestination?: () => void;
  onOpenChange: (open: boolean) => void;
}

export function ActivitiesSheetContent({
  localEnabled,
  localCategories,
  localDayPreferences,
  localPace,
  prerequisitesMet,
  hasDestination,
  onToggle,
  onSetLocalPace,
  onToggleCategory,
  onDayPreferenceChange,
  onOpenDestination,
  onOpenChange,
}: ActivitiesSheetContentProps) {
  return (
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
          onCheckedChange={onToggle}
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
        {/* Pace -- activities per day (generation target) */}
        <div>
          <h3 className={cn(DS.text.label, 'mb-2')}>Pace</h3>
          <div className="grid grid-cols-3 rounded-xl border-2 border-zinc-200 dark:border-white/15 overflow-hidden">
            {PACE_OPTIONS.map((option) => {
              const isSelected = localPace === option.value;
              const Icon = option.icon;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onSetLocalPace(isSelected ? null : option.value)}
                  className={cn(
                    'group flex flex-col items-center py-3 text-sm transition-colors',
                    'border-l border-zinc-200 dark:border-white/10 first:border-l-0',
                    isSelected
                      ? 'bg-emerald-500/15 text-emerald-400 font-semibold'
                      : 'text-zinc-400 hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900 dark:hover:border-white/40 dark:hover:bg-white/10 dark:hover:text-white'
                  )}
                >
                  <Icon
                    className={cn(
                      'mb-0.5 h-4 w-4 shrink-0 transition-colors',
                      isSelected
                        ? 'text-emerald-400'
                        : 'text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-white'
                    )}
                    strokeWidth={2.25}
                  />
                  <span>{option.label}</span>
                  <span className="text-xs opacity-70">{option.value}/day</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Activity Categories -- single flat grid */}
        <div>
          <div className="grid grid-cols-2 gap-2">
            {ALL_CATEGORIES.map((option) => {
              const isSelected = localCategories.includes(option.value);
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onToggleCategory(option.value)}
                  className={cn(
                    'flex items-center gap-2 px-3 py-3 rounded-lg text-sm font-medium',
                    'transition-all duration-150 text-left',
                    isSelected
                      ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-transparent'
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

        {/* Day preferences -- only when categories selected */}
        {localCategories.length > 0 && (
          <div>
            <h3 className={cn(DS.text.label, 'mb-2')}>
              Days per activity
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-500 mb-2">
              Leave at 0 for no preference
            </p>
            <div className="space-y-1">
              {localCategories.map((catValue) => {
                const catDef = ALL_CATEGORIES.find(c => c.value === catValue);
                return (
                  <div key={catValue} className="flex items-center justify-between py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-sm">{catDef?.icon || '\u{1F3F7}\uFE0F'}</span>
                      <span className="text-sm font-medium text-zinc-900 dark:text-white">
                        {catDef?.label || catValue}
                      </span>
                    </div>
                    <Stepper
                      value={localDayPreferences[catValue] || 0}
                      min={0}
                      max={7}
                      size="sm"
                      onChange={(val) => onDayPreferenceChange(catValue, val)}
                      label={`${catDef?.label || catValue} days`}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
