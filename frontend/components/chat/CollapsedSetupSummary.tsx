/**
 * CollapsedSetupSummary
 *
 * Single collapsed block replacing Setup assistant messages.
 * Shows: "Setup complete: Dubai · Jan 25-Feb 1 · 1 adult"
 * Expandable to show Configuration Snapshot (audit trail).
 */

'use client';

import { ChevronDown, Sparkles } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';
import type { ChatMessage } from '@/types/chat';
import type { DocumentTripInputs } from '@/types/document';

// =============================================================================
// TripBrief - Shows soft constraints as pills (replaces ConfigurationSnapshot)
// =============================================================================

interface TripBriefProps {
  tripInputs: DocumentTripInputs;
  executedTopics?: string[];
}

/**
 * TripBrief
 *
 * Shows the "Why & How" of the trip - soft constraints the AI is using:
 * - Activity interests (diving, hiking, etc.)
 * - Flight preferences (cabin class, direct only)
 * - Hotel preferences (min stars, amenities)
 * - Executed strategy topics (what specialists ran)
 *
 * Does NOT show redundant hard constraints (destination, dates, travelers)
 * since those are already visible in the Hero Header.
 */
function TripBrief({ tripInputs, executedTopics }: TripBriefProps) {
  // Extract soft constraints (preferences, not hard facts)
  const activities = tripInputs.activity_settings?.categories || [];
  const flightSettings = tripInputs.flight_settings;
  const hotelSettings = tripInputs.hotel_settings;
  const transportSettings = tripInputs.transport_settings;

  // Build preference pills
  const preferences: Array<{ label: string; variant: 'activity' | 'setting' | 'topic' }> = [];

  // Activity interests (with emoji - they already have emoji in the data)
  activities.forEach((cat) => {
    preferences.push({ label: cat, variant: 'activity' });
  });

  // Flight preferences (only non-default values)
  if (flightSettings?.cabin_class && flightSettings.cabin_class !== 'economy') {
    const label =
      flightSettings.cabin_class === 'business'
        ? '✈️ Business Class'
        : flightSettings.cabin_class === 'first'
          ? '✈️ First Class'
          : '✈️ Premium Economy';
    preferences.push({ label, variant: 'setting' });
  }
  if (flightSettings?.direct_only) {
    preferences.push({ label: '✈️ Direct flights only', variant: 'setting' });
  }

  // Hotel preferences
  if (hotelSettings?.min_stars && hotelSettings.min_stars >= 3) {
    preferences.push({ label: `⭐ ${hotelSettings.min_stars}+ star hotels`, variant: 'setting' });
  }
  if (hotelSettings?.amenities?.length) {
    hotelSettings.amenities.slice(0, 2).forEach((a) => {
      preferences.push({ label: `🏨 ${a}`, variant: 'setting' });
    });
  }

  // Transport preferences
  if (transportSettings?.car) preferences.push({ label: '🚗 Rental car', variant: 'setting' });
  if (transportSettings?.train) preferences.push({ label: '🚆 Train', variant: 'setting' });

  // Strategy topics (what AI is "thinking about")
  executedTopics?.forEach((topic) => {
    const formatted = topic.charAt(0).toUpperCase() + topic.slice(1).replace(/_/g, ' ');
    preferences.push({ label: `🤖 ${formatted}`, variant: 'topic' });
  });

  // Empty state
  if (preferences.length === 0) {
    return (
      <div className="mt-2 ml-4 pl-3 border-l-2 border-zinc-200 dark:border-zinc-800/50 animate-in slide-in-from-top-2 duration-200">
        <p className="text-xs text-zinc-500 italic">No specific preferences set</p>
      </div>
    );
  }

  return (
    <div className="mt-3 animate-in slide-in-from-top-2 duration-200">
      {/* Container card for visual grouping */}
      <div className={cn(
        'rounded-xl overflow-hidden',
        // Light: Subtle off-white card with crisp border
        'bg-zinc-50 border border-zinc-200',
        // Dark: Subtle dark panel
        'dark:bg-black/20 dark:border-white/10'
      )}>
        {/* Header */}
        <div className="px-3 pt-3 pb-2 flex items-center gap-1.5">
          <Sparkles className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
          <span className={cn(
            'text-[10px] font-bold uppercase tracking-wider',
            // Light: Dark grey for readability
            'text-zinc-600',
            // Dark: Softer grey
            'dark:text-zinc-400'
          )}>
            Trip Brief & Preferences
          </span>
        </div>

        {/* Preference pills - monochromatic design */}
        <div className="px-3 pb-3 flex flex-wrap gap-1.5">
          {preferences.map((pref, i) => (
            <span
              key={i}
              className={cn(
                'text-xs px-2.5 py-1 rounded-lg font-medium transition-colors',
                // All pills: Monochromatic zinc styling
                'bg-white dark:bg-transparent',
                'border border-zinc-200 dark:border-white/10',
                'text-zinc-600 dark:text-zinc-400'
              )}
            >
              {pref.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// CollapsedSetupSummary - Main component
// =============================================================================

interface CollapsedSetupSummaryProps {
  summaryText: string;
  originalMessages?: ChatMessage[];
  // Configuration snapshot for audit trail (prioritized over originalMessages)
  tripInputsSnapshot?: DocumentTripInputs;
  executedTopicsSnapshot?: string[];
  /**
   * Display variant:
   * - 'card': Full card with shadow (default, for desktop)
   * - 'compact': Thin divider style (for mobile post-plan)
   */
  variant?: 'card' | 'compact';
}

export function CollapsedSetupSummary({
  summaryText,
  originalMessages = [],
  tripInputsSnapshot,
  executedTopicsSnapshot,
  variant = 'card',
}: CollapsedSetupSummaryProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Handle click: toggle expand AND scroll right panel to top
  // This reinforces the connection between "Inputs" (left) and "Outputs" (right)
  const handleClick = () => {
    setIsExpanded(!isExpanded);
    // Scroll the right panel (plan-panel) to the top
    const planPanel = document.getElementById('plan-panel');
    if (planPanel) {
      planPanel.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // COMPACT VARIANT: Thin divider style for mobile post-plan
  // ─────────────────────────────────────────────────────────────────────────────
  if (variant === 'compact') {
    return (
      <div className="my-3">
        {/* Thin divider with centered "Setup complete" text */}
        <button
          type="button"
          onClick={handleClick}
          className="w-full flex items-center gap-3 py-2 text-xs text-zinc-400 dark:text-zinc-500 hover:text-zinc-600 dark:hover:text-zinc-400 transition-colors group"
        >
          {/* Left line */}
          <div className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800" />

          {/* Center content */}
          <div className="flex items-center gap-1.5 shrink-0">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span className="font-medium">Setup complete</span>
            <ChevronDown
              className={cn(
                'h-3 w-3 transition-transform duration-200',
                isExpanded && 'rotate-180'
              )}
            />
          </div>

          {/* Right line */}
          <div className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800" />
        </button>

        {/* Expanded content - same as card variant */}
        {isExpanded && tripInputsSnapshot && (
          <TripBrief tripInputs={tripInputsSnapshot} executedTopics={executedTopicsSnapshot} />
        )}

        {isExpanded && !tripInputsSnapshot && originalMessages.length > 0 && (
          <div
            className={cn(
              'mt-2 ml-4 pl-3 border-l-2 border-zinc-200 dark:border-zinc-800/50',
              'space-y-2 animate-in slide-in-from-top-2 duration-200'
            )}
          >
            {originalMessages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  'text-xs',
                  msg.role === 'user' ? 'text-zinc-700 dark:text-zinc-300' : 'text-zinc-500'
                )}
              >
                <span className="text-zinc-500 dark:text-zinc-600 font-medium">
                  {msg.role === 'user' ? 'You: ' : 'Assistant: '}
                </span>
                {msg.content}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // CARD VARIANT: System Status card design
  // ─────────────────────────────────────────────────────────────────────────────

  // Extract summary parts from summaryText for data display
  // Format: "Setup complete: Dubai · Jan 25-Feb 1 · 1 adult"
  const summaryParts = summaryText
    .replace(/^(Setup complete:|Trip configured:)\s*/i, '')
    .split(' · ')
    .filter(Boolean);
  const primaryInfo = summaryParts[0] || '';
  const secondaryInfo = summaryParts.slice(1).join(' · ');

  return (
    <div className="my-4 relative">
      {/* Visual divider line above - "chapter break" between Setup and Plan */}
      <div className="absolute -top-2 left-0 right-0 flex items-center gap-2">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-zinc-300 dark:via-zinc-700/60 to-transparent" />
      </div>

      {/* System Status Card */}
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          'w-full p-3 rounded-xl',
          'flex items-center justify-between',
          'text-left transition-colors cursor-pointer',
          // Light: Subtle grey card
          'bg-zinc-50 border border-zinc-200',
          'hover:border-zinc-300',
          // Dark: Transparent dark panel
          'dark:bg-white/[0.02] dark:border-white/10',
          'dark:hover:border-white/20',
          'group'
        )}
      >
        {/* Left: Status Indicator */}
        <div className="flex items-center gap-3">
          {/* Pulsing emerald dot */}
          <div className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] uppercase font-bold text-zinc-400 dark:text-zinc-500 tracking-wider">
              System Status
            </span>
            <span className="text-xs font-bold text-zinc-900 dark:text-white font-mono">
              CONFIG_READY
            </span>
          </div>
        </div>

        {/* Right: Summary Data */}
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
              {primaryInfo}
            </div>
            {secondaryInfo && (
              <div className="text-[10px] text-zinc-400 dark:text-zinc-500">
                {secondaryInfo}
              </div>
            )}
          </div>
          <ChevronDown
            className={cn(
              'h-4 w-4 text-zinc-400 dark:text-zinc-600 transition-transform duration-200',
              'group-hover:text-zinc-600 dark:group-hover:text-zinc-400',
              isExpanded && 'rotate-180'
            )}
          />
        </div>
      </button>

      {/* Expanded content - prioritize Trip Brief over original messages */}
      {isExpanded && tripInputsSnapshot && (
        <TripBrief tripInputs={tripInputsSnapshot} executedTopics={executedTopicsSnapshot} />
      )}

      {/* Fallback to original messages if no snapshot (backward compatibility) */}
      {isExpanded && !tripInputsSnapshot && originalMessages.length > 0 && (
        <div
          className={cn(
            'mt-2 ml-4 pl-3 border-l-2 border-zinc-200 dark:border-zinc-800/50',
            'space-y-2 animate-in slide-in-from-top-2 duration-200'
          )}
        >
          {originalMessages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'text-xs',
                msg.role === 'user' ? 'text-zinc-700 dark:text-zinc-300' : 'text-zinc-500'
              )}
            >
              <span className="text-zinc-500 dark:text-zinc-600 font-medium">
                {msg.role === 'user' ? 'You: ' : 'Assistant: '}
              </span>
              {msg.content}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default CollapsedSetupSummary;
