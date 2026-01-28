/**
 * CollapsedSetupSummary
 *
 * Single collapsed block replacing Setup assistant messages.
 * Shows: "Setup complete: Dubai · Jan 25-Feb 1 · 1 adult"
 * Expandable to show Configuration Snapshot (audit trail).
 */

'use client';

import { ChevronDown, MessageSquare, Sparkles } from 'lucide-react';
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
      <div className="mt-2 ml-4 pl-3 border-l-2 border-zinc-800/50 animate-in slide-in-from-top-2 duration-200">
        <p className="text-xs text-zinc-500 italic">No specific preferences set</p>
      </div>
    );
  }

  return (
    <div className="mt-2 ml-4 pl-3 border-l-2 border-zinc-800/50 animate-in slide-in-from-top-2 duration-200">
      <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-2 flex items-center gap-1.5">
        <Sparkles className="w-3 h-3" />
        Trip Brief & Preferences
      </div>
      <div className="flex flex-wrap gap-1.5">
        {preferences.map((pref, i) => (
          <span
            key={i}
            className={cn(
              'text-xs px-2 py-0.5 rounded-full transition-colors',
              pref.variant === 'activity' &&
                'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
              pref.variant === 'setting' &&
                'bg-blue-500/10 text-blue-400 border border-blue-500/20',
              pref.variant === 'topic' && 'bg-zinc-700/50 text-zinc-400 border border-zinc-600/30'
            )}
          >
            {pref.label}
          </span>
        ))}
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
}

export function CollapsedSetupSummary({
  summaryText,
  originalMessages = [],
  tripInputsSnapshot,
  executedTopicsSnapshot,
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

  return (
    <div className="my-4 relative">
      {/* Visual divider line above - "chapter break" between Setup and Plan */}
      <div className="absolute -top-2 left-0 right-0 flex items-center gap-2">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-zinc-700/60 to-transparent" />
      </div>

      {/* Collapsed header */}
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 rounded-lg',
          'text-left text-xs transition-all duration-200',
          'bg-zinc-800/40 hover:bg-zinc-800/60',
          'border border-zinc-700/40',
          'group'
        )}
      >
        <MessageSquare className="h-3.5 w-3.5 text-zinc-500 flex-shrink-0" />
        <span className="flex-1 text-zinc-400 truncate">
          {summaryText.replace('Setup complete:', 'Trip configured:')}
        </span>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-zinc-600 transition-transform duration-200',
            'group-hover:text-zinc-400',
            isExpanded && 'rotate-180'
          )}
        />
      </button>

      {/* Expanded content - prioritize Trip Brief over original messages */}
      {isExpanded && tripInputsSnapshot && (
        <TripBrief tripInputs={tripInputsSnapshot} executedTopics={executedTopicsSnapshot} />
      )}

      {/* Fallback to original messages if no snapshot (backward compatibility) */}
      {isExpanded && !tripInputsSnapshot && originalMessages.length > 0 && (
        <div
          className={cn(
            'mt-2 ml-4 pl-3 border-l-2 border-zinc-800/50',
            'space-y-2 animate-in slide-in-from-top-2 duration-200'
          )}
        >
          {originalMessages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'text-xs',
                msg.role === 'user' ? 'text-zinc-300' : 'text-zinc-500'
              )}
            >
              <span className="text-zinc-600 font-medium">
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
