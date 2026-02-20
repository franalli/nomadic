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
  onOpenFlights: () => void;
  onOpenStays: () => void;
  onOpenActivities: () => void;
  toast: (message: string) => void;
}

export function ChatSuggestionChips({
  effectiveSuggestions,
  suggestionChips,
  suggestedResponseMeta,
  isLoading,
  bookingTypes,
  onUpdateFlightSettings,
  onUpdateBookingTypes,
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
      className="flex flex-wrap justify-center gap-2 pt-3 pb-1 px-2"
    >
      {chips.map((chip, idx) => {
        const isCta = chip.chip_type === 'cta';
        const isPlanningTrigger = isCta || /\bplan\b/i.test(chip.message);
        const isSheetAction = chip.action_type === 'open_pill';

        // Action routing: open_pill -> sheet, send_message -> chat
        const handleChipClick = () => {
          if (chip.action_type === 'open_pill' && chip.action_target) {
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

            const opener = sheetMap[chip.action_target];
            if (opener) {
              opener();
            } else {
              debugLog(`[ChatPanel] Unknown sheet target: ${chip.action_target}`);
              onSendMessage(chip.message, { suggestionClicked: chip.message });
            }
          } else if (chip.action_type === 'trigger_action') {
            const handled = handleSuggestionTriggerAction({
              actionTarget: chip.action_target,
              bookingTypes,
              onUpdateFlightSettings,
              onUpdateBookingTypes,
              ensureSettingsFlushed: () => useDocumentStore.getState().ensureSettingsFlushed(),
              toast,
            });
            if (!handled) {
              debugLog(`[ChatPanel] Unknown trigger_action target: ${chip.action_target}`);
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
