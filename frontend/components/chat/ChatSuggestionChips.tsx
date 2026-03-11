/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { SlidersHorizontal, Sparkles } from 'lucide-react';

import { debugLog } from '@/lib/debug';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type {
  BookingTypes,
  FlightSettings,
  SuggestionChip,
  SuggestionChipMeta,
} from '@/types/document';
import type { SheetType } from '@/types/sheets';

import { handleSuggestionTriggerAction } from './suggestion-actions';

interface ChatSuggestionChipsProps {
  effectiveSuggestions: string[];
  suggestionChips: SuggestionChip[];
  suggestedResponseMeta: SuggestionChipMeta[];
  isLoading: boolean;
  bookingTypes?: BookingTypes;
  onUpdateFlightSettings?: (settings: Partial<FlightSettings>) => void;
  onUpdateBookingTypes?: (settings: Partial<BookingTypes>) => void;
  onOpenSheet?: (sheet: SheetType) => void;
  onSendMessage: (message: string, options?: { suggestionClicked?: string }) => void;
  onConfirmReset?: () => void;
  onOpenFlights: () => void;
  onOpenStays: () => void;
  onOpenActivities: () => void;
  toast: (message: string) => void;
}

type ResolvedChipAction = {
  actionType: SuggestionChip['action_type'];
  actionTarget: string | null;
};

const OPEN_PILL_TARGETS = new Set([
  'dates',
  'origin',
  'destination',
  'travelers',
  'budget',
  'flights',
  'stays',
  'activities',
]);

const TRIGGER_ACTION_TARGETS = new Set(['set_direct_flights_only', 'confirm_reset']);

const ACTION_TARGET_ALIASES: Record<string, string> = {
  activity: 'activities',
  activity_sheet: 'activities',
  date: 'dates',
  departure: 'origin',
  departure_city: 'origin',
  direct_flights_only: 'set_direct_flights_only',
  direct_only: 'set_direct_flights_only',
  flight_origin: 'origin',
  hotel: 'stays',
  hotels: 'stays',
  stay: 'stays',
  traveller: 'travelers',
  travellers: 'travelers',
};

const FALLBACK_ACTION_BY_CATEGORY: Record<string, ResolvedChipAction> = {
  plan_dates_refine: { actionType: 'open_pill', actionTarget: 'dates' },
  plan_budget: { actionType: 'open_pill', actionTarget: 'budget' },
  plan_activity_explore: { actionType: 'open_pill', actionTarget: 'activities' },
  plan_activities: { actionType: 'open_pill', actionTarget: 'activities' },
  plan_hotel_stars: { actionType: 'open_pill', actionTarget: 'stays' },
  plan_hotel_pref: { actionType: 'open_pill', actionTarget: 'stays' },
  plan_hotels_compare: { actionType: 'open_pill', actionTarget: 'stays' },
  plan_flights_hint: { actionType: 'open_pill', actionTarget: 'origin' },
  plan_flight_pref: { actionType: 'trigger_action', actionTarget: 'set_direct_flights_only' },
  plan_flight_direct: { actionType: 'trigger_action', actionTarget: 'set_direct_flights_only' },
};

const FALLBACK_ACTION_BY_TEXT: Array<{ pattern: RegExp; action: ResolvedChipAction }> = [
  { pattern: /set my departure city|departure city/i, action: { actionType: 'open_pill', actionTarget: 'origin' } },
  { pattern: /change my dates|set dates|travel dates/i, action: { actionType: 'open_pill', actionTarget: 'dates' } },
  { pattern: /set my budget|budget/i, action: { actionType: 'open_pill', actionTarget: 'budget' } },
  { pattern: /browse activities|must-do activities|activities in/i, action: { actionType: 'open_pill', actionTarget: 'activities' } },
  { pattern: /compare hotel options|5-star hotels|hotel options/i, action: { actionType: 'open_pill', actionTarget: 'stays' } },
  { pattern: /direct flights only/i, action: { actionType: 'trigger_action', actionTarget: 'set_direct_flights_only' } },
];

function normalizeActionTarget(
  actionType: SuggestionChip['action_type'],
  actionTarget: string | null | undefined
): string | null {
  if (!actionTarget) {
    return null;
  }
  const canonical = ACTION_TARGET_ALIASES[actionTarget.toLowerCase()] ?? actionTarget.toLowerCase();
  if (actionType === 'open_pill') {
    return OPEN_PILL_TARGETS.has(canonical) ? canonical : null;
  }
  if (actionType === 'trigger_action') {
    return TRIGGER_ACTION_TARGETS.has(canonical) ? canonical : null;
  }
  return canonical;
}

function resolveChipAction(chip: SuggestionChip): ResolvedChipAction {
  // Pre-plan date chips are executable prompts (e.g., "Feb 27-01"),
  // so clicking should run extraction, not open the date sheet.
  if (
    chip.category === 'date_prompt' || chip.category === 'date_contextual'
  ) {
    return {
      actionType: 'send_message',
      actionTarget: null,
    };
  }

  const explicitTarget = normalizeActionTarget(chip.action_type, chip.action_target);
  if (chip.action_type !== 'send_message' && explicitTarget) {
    return {
      actionType: chip.action_type,
      actionTarget: explicitTarget,
    };
  }

  if (chip.category && FALLBACK_ACTION_BY_CATEGORY[chip.category]) {
    return FALLBACK_ACTION_BY_CATEGORY[chip.category];
  }

  for (const rule of FALLBACK_ACTION_BY_TEXT) {
    if (rule.pattern.test(chip.message)) {
      return rule.action;
    }
  }

  return {
    actionType: 'send_message',
    actionTarget: null,
  };
}

export function ChatSuggestionChips({
  effectiveSuggestions,
  suggestionChips,
  suggestedResponseMeta,
  isLoading,
  bookingTypes,
  onUpdateFlightSettings,
  onUpdateBookingTypes,
  onConfirmReset,
  onOpenSheet,
  onSendMessage,
  onOpenFlights,
  onOpenStays,
  onOpenActivities,
  toast,
}: ChatSuggestionChipsProps) {
  if (effectiveSuggestions.length === 0 || isLoading) return null;

  // Prefer structured chips if available, fallback to legacy string array
  const chips: SuggestionChip[] = suggestionChips.length > 0
    ? suggestionChips
    : effectiveSuggestions.map((text, i) => ({
        message: text,
        action_type: 'send_message' as const,
        action_target: null,
        chip_type: suggestedResponseMeta[i]?.chip_type || 'follow_up',
        category: suggestedResponseMeta[i]?.category || '',
        icon: suggestedResponseMeta[i]?.icon || null,
      }));

  return (
    <div
      key={`suggestions-container-${effectiveSuggestions.length}`}
      className="flex gap-2 overflow-x-auto overscroll-x-contain px-2 pb-1 pt-3 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
    >
      {chips.map((chip, idx) => {
        const resolvedAction = resolveChipAction(chip);
        const isCta = chip.chip_type === 'cta';
        const isPlanningTrigger = isCta
          || chip.category.startsWith('plan_')
          || resolvedAction.actionType === 'trigger_action';
        const isSheetAction = resolvedAction.actionType === 'open_pill';

        // Action routing: open_pill -> sheet, send_message -> chat
        const handleChipClick = () => {
          if (resolvedAction.actionType === 'open_pill' && resolvedAction.actionTarget) {
            const sheetMap: Record<string, () => void> = {
              'dates': () => onOpenSheet?.('dates'),
              'origin': () => onOpenSheet?.('origin'),
              'destination': () => onOpenSheet?.('destination'),
              'travelers': () => onOpenSheet?.('travelers'),
              'budget': () => onOpenSheet?.('budget'),
              'flights': () => onOpenFlights(),
              'stays': () => onOpenStays(),
              'activities': () => onOpenActivities(),
            };

            const opener = sheetMap[resolvedAction.actionTarget];
            if (opener) {
              opener();
            } else {
              debugLog(`[ChatPanel] Unknown sheet target: ${resolvedAction.actionTarget}`);
              onSendMessage(chip.message, { suggestionClicked: chip.message });
            }
          } else if (resolvedAction.actionType === 'trigger_action') {
            const handled = handleSuggestionTriggerAction({
              actionTarget: resolvedAction.actionTarget,
              bookingTypes,
              onUpdateFlightSettings,
              onUpdateBookingTypes,
              onConfirmReset,
              ensureSettingsFlushed: () => useDocumentStore.getState().ensureSettingsFlushed(),
              toast,
            });
            if (!handled) {
              debugLog(`[ChatPanel] Unknown trigger_action target: ${resolvedAction.actionTarget}`);
              onSendMessage(chip.message, { suggestionClicked: chip.message });
            }
          } else {
            onSendMessage(chip.message, { suggestionClicked: chip.message });
          }
        };

        return (
          <button
            key={`sugg-${chip.message.slice(0, 20)}-${idx}`}
            type="button"
            onClick={handleChipClick}
            className={cn(
              'px-4 py-2.5 rounded-lg',
              'shrink-0 whitespace-nowrap',
              'text-xs font-bold uppercase tracking-wide',
              'transition-all duration-150 active:scale-95',
              'max-w-full truncate',
              isPlanningTrigger ? [
                'bg-emerald-50 dark:bg-emerald-950/30',
                'border-2 border-emerald-500/40 dark:border-emerald-500/30',
                'text-emerald-700 dark:text-emerald-400',
                'hover:bg-emerald-100 hover:border-emerald-500',
                'dark:hover:bg-emerald-900/40 dark:hover:border-emerald-400/50',
              ] : [
                'bg-white dark:bg-white/5',
                'border-2 border-zinc-200 dark:border-white/15',
                'text-zinc-600 dark:text-zinc-400',
                'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                'dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white',
              ]
            )}
          >
            {isSheetAction && (
              <SlidersHorizontal className="w-3 h-3 mr-1.5 inline-block" />
            )}
            {isPlanningTrigger && !isSheetAction && (
              <Sparkles className="w-3 h-3 mr-1.5 inline-block" />
            )}
            {chip.message}
          </button>
        );
      })}
    </div>
  );
}
